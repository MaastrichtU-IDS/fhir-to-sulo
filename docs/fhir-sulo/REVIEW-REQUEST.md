# Consolidated review request — clinical and ontology interpretations

**Status:** OPEN — awaiting the human clinical/ontology reviewer
**Answered:** R1 · R1b · R1d · R2 · R4 · R5 · R6 · R7 · R8a · R10 · R11.
**3 of 12 remain open:** R8b, R9, R12 — R3 is answered bar two residues; R7 is signed off; R8a is answered and applied (DR-010, OntoClean), leaving only R8b's merge question. R5b closed with nothing to implement; **R5c withdrawn** — its premise was false.
R1's namespace `https://w3id.org/ontostart/fhir2sulo/` is applied; R4, R6 and R11 are being
applied to the maps and shapes.
**Raised by:** Agent 1 (integration lead)
**Opened:** 2026-09-29
**Gate:** 0 (plan §4 Gate 0 requires reviewer sign-off on the record/fact distinction
and the PRO/SOLID target patterns before a map is marked usable)

> **None of the items below are approved.** Plan §2: "The human ontology/clinical reviewer
> approves the domain typing and status policies before a map is marked usable." Plan §6
> rule 4: any disagreement becomes a decision record with an example graph.
>
> Engineering continues in parallel against the concept note's literal example graphs, with
> each item below parameterised so that a reviewer answer flips behaviour without re-authoring
> maps. Where an item is unresolved, the affected output is held at `source-only` rather than
> asserted. No item is being treated as settled by default.

## How to answer

Reply per item with **A**, **B**, … or your own wording. Anything you do not answer stays
open and its dependent gate stays blocked. Items are ordered by how much is blocked behind them.

---

## R1 — The domain vocabulary is a placeholder and needs an owner  ✅ ANSWERED

> **Answered 2026-09-30 — option A**, mint a project-local vocabulary.
> Namespace: **`https://w3id.org/ontostart/fhir2sulo/`**, applied 2026-09-30. The reviewer
> first wrote `wi3d.org`; queried before applying rather than after, because it is a graph-key
> input and correcting it later would have been a second migration. Measured effect: every
> quality IRI re-keyed, every person IRI byte-identical apart from the prefix.
>
> **Option B was withdrawn as offered.** `sulo2snomed.ttl` (25 mappings) covers only SNOMED's
> top-level hierarchies, and `sulo2sphn.ttl` types `sphn#BloodPressure` as
> `sulo:InformationObject`. **Neither maps anything to `sulo:Quality`**, so binding to them
> would collapse the quality and quantity layers that the SOLID pattern separates.
>
> **R1b answered:** the LOINC code denotes the **measurement result**; the quality is a
> separate commitment on the same entry. Recorded as `code_denotes: "result_class"`.
>
> **R1d answered:** yes — verified in the emitted graph, the record is a
> `sulo:InformationObject` that `sulo:refersTo` the event.
>
> **Successor recorded:** RAG over OMOP vocabularies with LLM reranking, out of scope for
> Gates 0–4. Detail and the two properties that keep it droppable-in: DR-008.

**Blocks:** Gate 2, Gate 3, and every target shape. **Highest priority.**

The concept note's worked examples use an `ex:` namespace for every domain class:
`ex:RenalFiltrationQuality`, `ex:EGFRResult`, `ex:ObservationRecord`, `ex:ClinicalEncounter`,
`ex:PatientRole`, `ex:ClinicianRole`, `ex:Person`. §4 describes this as "the `ex:` vocabulary
supplies domain classes and stable project IRIs", but does not say what that vocabulary
actually is.

SULO deliberately does not supply these — it is an upper-level ontology with 17 classes
(verified, DR-002). The pilot cannot emit `ex:` placeholders into a semantic graph.

**Options**

- **A.** Mint a small project-local domain vocabulary in this repository, with a stable
  namespace you nominate, defined as subclasses of the SULO classes already verified.
  Smallest scope; the pilot owns and versions it.
- **B.** Reuse an existing clinical ontology (SNOMED CT, LOINC-as-ontology, or the
  `sulo2snomed` / `sulo2sphn` mappings already in `AIDAVA-DEV/sulo/mapping/`) and bind
  domain classes to it through the reviewed code interpretation table.
- **C.** A hybrid: project-local classes now, each carrying a mapping annotation to the
  external ontology, resolved later.

**What we need from you:** the option, and if A or C, the namespace to mint under.

**The concrete instance awaiting you (R1b):** three domain typings are currently transcribed
from the concept note's examples and are *not* a reviewed commitment —
`33914-3 → ex:EGFRResult` with quality `ex:RenalFiltrationQuality`, and the systolic/diastolic
equivalents for `8480-6` / `8462-4`. Approve or correct them. Note the quality classes interact
with **R4**: they presumably need to be `sulo:Quality`, not bare `sulo:Feature`.

**R1d — what class is the *Encounter record*?** §4 names `ex:ObservationRecord`; §6 names
nothing for the Encounter equivalent. `ex:EncounterRecord` is emitted as a placeholder.

**Sequencing consequence, established since:** answering R1 **re-keys every quality IRI**, not
only R2, because the quality class IRI is one of the quality key's inputs. A test asserts this
and also proves nothing else moves. So R1 and R2 are best answered together, and both are
graph migrations rather than configuration changes.

**Meanwhile:** target shapes are authored against SULO upper-level terms only, with domain
typing emitted through a single indirection point. This is verified, not asserted: a test
hard-codes a domain IRI into a schema and requires the build to fail, and another swaps the
whole vocabulary and requires no schema to change.

---

## R2 — Quality identity: does a quality persist across observations?  ✅ ANSWERED

> **Answered 2026-09-30 — option B (per-observation), provisionally.**
>
> The reviewer was explicit that the underlying question is *not* resolved: whether there is a
> single quality of a kind for an individual or several distinct instances "needs revisiting
> in a coherent theory, compared against other upper-level ontologies". One per event with its
> associated value was chosen as **safest**, not as settled.
>
> Recorded in `policies/identity-policy.v1.json` with that caveat, and a test fails if the
> caveat is ever dropped — a provisional answer quietly becoming a conclusion is the failure
> mode here. Both modes stay implemented; switching re-keys every quality IRI.
>
> **No emitted triple moved.** The fixtures were already generated under per-observation, so
> the policy now states what was already true; `build.py --check` reports no drift on either
> the source or the expected graphs.

**Blocks:** Gate 2 node-key rules, Gate 4 idempotence and correction.
Named as a Gate 0 decision in both documents (concept note §8.2, plan Gate 0).

Concept note §4: "The quality URI is reused under a documented *quality identity policy* only
when the project intends one persisting renal-quality entity for that patient. Otherwise key it
by observation, time, and observable code so independent records do not merge unknowingly."

**Options**

- **A. Persisting quality.** One `RenalFiltrationQuality` per patient; successive eGFR results
  all `refersTo` it. Reads naturally ("this patient's renal filtration"), and supports
  trend queries over one entity. Risk: merges records that may not be commensurable
  (different methods, different labs), and a correction to one observation touches a
  shared node.
- **B. Observation-scoped quality.** Key by `(patient, observable code, effective time,
  observation version)`. No unintended merging; correction is cleanly scoped to one resource
  version. Cost: no single entity to hang a trend off; consumers must join.

**What we need from you:** A or B, and if A, what evidence justifies merging two observations
onto one quality (same code only? same code and method? same code, method and specimen?).

**Meanwhile:** implemented as a switchable policy with **both** behaviours and a deliberately
unset default that *rejects every request*, so no run can silently pick one.

**Two things established since this item was written:**

- **Your answer moves every quality IRI**, because the two modes key on different inputs.
  Person IRIs are unaffected. This is a graph migration, not a configuration change — it has to
  be sequenced, not just switched.
- Person IRIs are **stable across unrelated policy edits**: seven edits (version bumps on all
  three tables, adding a code entry, approving a unit, rewording prose, and answering this very
  question) leave every person IRI byte-identical. So answering this does not disturb anything
  else.

**R2b — related, not blocking Gates 0–4.** What counts as recorded evidence for merging two
references *across sources* into one person? Currently impossible by construction: the service
has no merge rule and an empty `accepted_merge_evidence` list, guarded by a test. With synthetic
single-source data this never arises, but it will before any clinical use.

---

## R3 — Status and `value[x]` interpretation policy  ✅ ANSWERED (two residues)

> **Answered 2026-10-01 — "confirm all", plus `amended`/`corrected` eligible.**
>
> Every row that carried a value awaiting confirmation is confirmed; those outcomes are now the
> reviewer's rather than engineering's holding position. Recorded in
> `profiles/fhir-r4-pilot.json` under `reviewer_decisions`.
>
> **`Observation.amended` and `corrected` are ELIGIBLE.** FHIR's `status` conflates two axes —
> verification (`registered` → `preliminary` → `final`) and revision (`final` →
> `amended`/`corrected`). The revision axis does not reduce reliability. Holding them at
> `source-only` applied the verification axis's caution to a position on the revision axis, and
> meant a **correction never reached the semantic layer**: v2 replaced v1's graph and then
> asserted nothing. `preliminary` and `registered` stay `source-only` — those *are* verification
> states. `entered-in-error` stays `source-only`: retraction, not revision.
>
> **Correction, measured 2026-10-01.** When this answer was recorded I stated the consequence
> as "an amendment touching only a `source_only` element yields a new graph version with
> **identical triples**". That is **false** under the quality identity mode R2 actually chose.
> Measured on `egfr-corrected` (v2) against `egfr-amended` (v3, which adds only an
> `Observation.note`):
>
> | | differing triples |
> | --- | ---: |
> | `prov:wasDerivedFrom` naming `_history/2` vs `/3` | 4 — correct and unavoidable |
> | **the quality node** | **10** |
> | total | 14 |
>
> Under `per-observation` the quality is keyed by source version, so **a purely administrative
> amendment mints a new `RenalFiltrationQuality` individual for the patient** — a new
> `sulo:Quality`, a new `isFeatureOf`/`hasFeature` pair, and the result's `refersTo` repointed.
> The patient's renal filtration did not change because someone added a note.
>
> The store behaviour R3 relied on is unaffected — it reports a replacement either way, because
> `source_json_digest` is a graph-key content field — but the reason I gave was not the
> operative one.
>
> **This is new evidence about R2, which was answered provisionally**, with the explicit
> instruction that the caveat must not quietly become a conclusion. It is harder to justify
> than the correction case: a correction minting a new quality is at least arguable, an
> administrative note doing so is less so. Under `persistent-per-person-code` only the 4
> provenance triples differ. Raised for the reviewer's attention; **no behaviour changed on the
> strength of it.**
>
> ### Two residues still open
>
> 1. **A `finished` Encounter with an open-ended period.** Valid FHIR, clinically incoherent. No
>    current value to confirm and no fixture fabricates it. Reject, or represent?
> 2. **The comparator and N4 `Observation.method`** — both still `rejected`. These were new
>    *proposals*, not rows awaiting confirmation, so "confirm all" did not cover them. See below.

**Blocks:** Gate 2 negative fixtures. Concept note §8.3 requires explicit outcomes.

Each row needs an outcome: **mapped**, **source-only**, or **rejected**. The concept note
specifies some directly (§4 "Failure variants"); those are marked *proposed from the note*.
The rest are genuinely open.

| Case | Proposed | Source |
| --- | --- | --- |
| `status = entered-in-error` | no clinical quantity; source record retained | note §2, §4 — confirm |
| `dataAbsentReason` present | no numeric `hasValue`; component record retained | note §4 — confirm |
| `valueQuantity.comparator` (e.g. `<`) | requires a qualified-value mapping | note §4 says "requires"; **what is the qualified-value pattern in SULO?** open |
| missing / unrecognised UCUM unit | **open** — note §4 says it fails the numeric target shape (`rejected`), but `source-only` is equally defensible and parallels `dataAbsentReason`. Visibly different graphs for the same input. | note §4 vs consistency |
| unit needs conversion (e.g. kPa → `mm[Hg]`) | **open** — currently never converted, conversion disabled | not specified |
| unknown or unmapped LOINC code | **open** — source-only or rejected? | not specified |
| `status = preliminary` | **open** | not specified |
| `status = amended` / `corrected` | **open** — treat as a new version, or as current? | not specified |
| `status = registered` | **open** | not specified |
| Encounter `status = in-progress` | **open** — §6 says only what it is *not* ("not treated as a finished interval"). Pinned conservatively as `source-only` pending your answer. A policy here touches R5, because a `StartTime` with no `EndTime` is exactly the closed-world case. | note §6 says nothing positive |
| Encounter `period` with no end | **open** — §2 requires preserving unknown endpoints, which argues for *representable* rather than rejected. Currently paired only with `in-progress`. Interacts with R5. | not specified |
| date-only `effective[x]` (e.g. `2026-09-02`) | **proposed `source-only`, derived not chosen.** The reviewer ruled *"date is not an instant"*. SULO's `Time` is a disjoint union of `Duration`/`TimeInstant`/`TimeInterval`; `Duration` is an elapsed amount, and `TimeInterval` requires a `StartTime` and an `EndTime` which are themselves instants — so deriving one means inventing a timezone the source never gave. Bare `Time` repeats the bare-`Feature` mistake R4 rejected. **No branch fits without fabricating.** DR-009. | reviewer 2026-09-30 + derivation |
| `finished` Encounter *with* an open-ended period | **open** — valid FHIR, clinically incoherent. No fixture fabricates this; say whether it should be rejected or represented. | not specified |

**What we need from you:** an outcome for every **open** row, and confirmation of the proposed
ones. The comparator row additionally needs a modelling answer, not just an outcome.

**Meanwhile:** every open row is held at `rejected` with an explicit diagnostic naming this
item, so no unqualified assertion can escape while the question is open.

---

## R4 — `sulo:Quality` vs bare `sulo:Feature` for the observed quality  ✅ ANSWERED

> **Answered 2026-09-30 — A, `sulo:Quality`.** *"we should not use feature -> it should go to
> a more specific class eg. sulo:Quality."* Ratifies what the maps already emit, and sanctions
> the deliberate divergence from the concept note's literal `a sulo:Feature` in §4.

**Blocks:** Gate 2 target shape. Arises from the SULO 0.2.12 axioms (DR-002).

Concept note §4 types the eGFR referent `a sulo:Feature, ex:RenalFiltrationQuality`.
But in SULO 0.2.12:

```turtle
sulo:Feature owl:disjointUnionOf ( sulo:Capability sulo:InformationObject sulo:Quality sulo:Role ) .
sulo:Quality rdfs:subClassOf sulo:Feature ;
    rdfs:comment "A quality is a feature that is intrinsically associated with its bearer (or its parts)."
```

`Feature` is a disjoint union of four branches, so typing an individual as bare `Feature`
leaves it unpartitioned — a reasoner cannot place it, and it is not wrong so much as
under-specified. `sulo:Quality` appears to be the intended branch for a physiological
characteristic of a patient.

**Options** — **A.** use `sulo:Quality`; **B.** keep bare `sulo:Feature` for a stated reason.

> **Currently emitted: A.** This was not stated when the item was written, and should have
> been. The maps emit
> `ex:quality-… a ex:RenalFiltrationQuality, sulo:Quality`, which **diverges from the concept
> note's literal `a sulo:Feature`** in §4. Engineering chose the more specific branch because
> bare `Feature` leaves the individual outside the disjoint union, but that is a choice the
> reviewer owns.
>
> So the real question is: **ratify what is emitted, or revert to the note's text?**

**What we need from you:** A or B.

---

## R5 — Closed-world shape strictness vs SULO's open-world existentials  ✅ ANSWERED

> **Answered — C, a per-axiom split.** Neither row was answered in isolation:
>
> | row | axiom | answer | how |
> | --- | --- | --- | --- |
> | 1 | `Quantity ⊑ isFeatureOf some (Object ⊔ Process)` | **A — materialize** | via **R11**: *"the results … are features of the individual"* |
> | 2 | `TimeInstant ⊑ hasPart some Unit` | **B — relax** | *"time instants are specified in the has value datatype"* |
>
> Row 2's reasoning: the unit of a time instant is carried by the `xsd` datatype on
> `sulo:hasValue`, which SULO restricts to `xsd:dateTime` or `xsd:dateTimeStamp`. An explicit
> `sulo:Unit` part would restate in RDF what the literal's datatype already fixes.
>
> The policy mode is now `quantity-bearer-only` — a mode Agent 6 had created to *name* this
> position before the reviewer arrived at it. Real map output conforms under it. The unset
> guarantee survives: an unanswered policy still refuses every spelling, now tested against a
> synthetic unset copy rather than the shipped file.
>
> ### R5b — OPEN, raised by this answer
>
> If the datatype carries the specification, **the choice of datatype becomes load-bearing.**
> We emit `xsd:dateTime`; concept note §4's schematic uses `xsd:dateTimeStamp`. The difference
> matters precisely under this answer: `dateTimeStamp` **requires** a timezone, `dateTime`
> permits one to be absent — so `dateTime` can express an under-specified instant, which is
> what the datatype was relied on to prevent.
>
> But a blanket `dateTimeStamp` would be wrong: FHIR `dateTime` legitimately permits a value
> with no offset, and §2 requires preserving temporal precision, so asserting an offset the
> source did not carry would be a fabrication.
>
> **R5b: instructed to apply, and it cannot be applied.** Measured against the live engine
> (CD-7, DR-207, 12 tests). The materializer re-emits the bound source term verbatim, so a
> target declaring `xsd:dateTimeStamp` still emits `xsd:dateTime`; and declaring it anyway
> makes the graph **fail reverse-validation against the schema that produced it**. The source
> RDF is not ours to re-type either — HL7's own Turtle types an offset-bearing value as plain
> `xsd:dateTime`, and re-typing would break the oracle.
>
> **R5 row 2's answer stands** — no unit is emitted. But its reasoning is weaker than it reads:
> the datatype is `xsd:dateTime` for *every* instant, so it does not distinguish a specified
> instant from an under-specified one. What carries the offset is the **lexical form**, and
> nothing requires one to be present. The offset is preserved when present and never invented.
>
> ### R5c — WITHDRAWN. Its premise was false, and the premise was mine.
>
> R5c asked how to treat an offsetless instant. **There are none.** FHIR R4's `dateTime` regex
> puts the timezone group inside the `T` group and does not make it optional, so
> `2026-09-02T14:00:00` is not conformant R4. Anything coarser renders `xsd:date` and is not an
> instant at all (DR-009).
>
> I proposed R5b on the premise that FHIR permits an offsetless clock time, then wrote CD-7
> criticising your reasoning on the same false premise. **Your reasoning was right**: every
> instant that reaches the semantic layer carries an offset, so the literal does specify it.
> Both the proposal and the criticism are withdrawn; CD-7 is corrected.
>
> Nothing to implement, and nothing further to decide here. Now asserted on emitted output by
> `test_every_emitted_instant_carries_an_offset.py`, which also re-checks the R4 regex so that
> if FHIR ever relaxed it, the test names what needs revisiting.


**Blocks:** Gate 2 and Gate 3 target validation. Arises from DR-002 axioms 2, 4 and 5.

SULO states several existential restrictions that an OWL reasoner satisfies silently but a
ShEx/SHACL target shape will flag as missing:

| Axiom | Concept note example | Tension |
| --- | --- | --- |
| `Quantity ⊑ hasPart some Unit` | eGFR quantity has an explicit UCUM unit ✓ | none |
| `Quantity ⊑ InformationObject ⊑ Feature ⊑ isFeatureOf some (Object ⊔ Process)` | `ex:egfr-result-456` has **no** `isFeatureOf` | reasoner infers an anonymous bearer; a shape check sees an omission |
| `TimeInstant ⊑ Time ⊑ Quantity ⊑ hasPart some Unit`, and `Time disjointWith Unit` | `ex:time-egfr-456` has **no** unit part | same, and a time instant cannot be its own unit |

**Options**

- **A. Materialize explicitly.** Emit `isFeatureOf` on quantities and an explicit time unit,
  so the graph is closed-world complete and shapes can be strict. More triples; the extra
  assertions must themselves be justified.
- **B. Relax the shapes.** Shapes check only what the maps promise; the reasoner covers the
  rest. Fewer triples, but the acceptance criterion "no orphan quantity/unit nodes"
  (Gate 2) gets weaker.
- **C. Per-axiom split** — e.g. explicit time unit (A) but leave `isFeatureOf` implicit (B).

**What we need from you:** A, B, or C with the split.

---

## R6 — Person typing and the `Feature` / `SpatialObject` disjointness  ✅ ANSWERED

> **Answered 2026-09-30 — `sulo:SpatialObject`.** *"a person is a Spatial Object."*
> A **change** from the emitted bare `sulo:Object`.
>
> Verified safe before dispatch: `SpatialObject ⊑ Object`, so `hasParticipant`'s range and the
> `Feature ⊑ isFeatureOf some (Object ⊔ Process)` restriction both still hold. Watch
> `SpatialObject ⊑ (hasPart only SpatialObject)`.
>
> **This restores the OWL guard CD-6 recorded as missing.** Under `SpatialObject` a person also
> typed as a Quality or Role is inconsistent and HermiT catches it; bare `Object` could not,
> because `Quality ⊑ Feature ⊑ Object`. CD-6 closes.

**Blocks:** Gate 2, Gate 3 reasoning checks. Depends on R1.

`sulo:Feature owl:disjointWith sulo:SpatialObject`, and `sulo:Feature rdfs:subClassOf sulo:Object`.
So the class chosen for a patient determines whether the graph stays consistent: a patient
typed as a `sulo:SpatialObject` can bear features, but must never itself be typed as any
`Feature` branch.

The concept note writes `ex:person-p123 a ex:Person` without saying where `ex:Person` sits
under SULO.

> **Currently emitted: bare `sulo:Object`** (`ex:person-… a ex:Person, sulo:Object`). Not
> stated when the item was written; stating it now because it is the option with *fewer*
> guarantees, and the reviewer should not ratify it unknowingly.

**The measured consequence**, four tests, all passing:

| person typed | a person also typed as a Role is… |
| --- | --- |
| `sulo:SpatialObject` | **inconsistent** — HermiT catches it |
| bare `sulo:Object` *(current)* | **consistent** — no OWL guard at all |

Because `Quality ⊑ Feature ⊑ Object`, bare `Object` cannot clash with a Feature branch. Both
typings are fine on their own; the difference is only whether the reasoner can catch a
misclassification. SHACL catches it either way, so nothing reaches the store — but the
acceptance matrix's "an OWL reasoner checks consistency" is only true under
`sulo:SpatialObject`. See CD-6.

**What we need from you:** the SULO parent for the patient/practitioner class —
`sulo:SpatialObject`, bare `sulo:Object`, or something else. (This is the specific form R1
takes for the person class, and Gate 3's reasoner check depends on it.)

---

## R7 — Record/fact distinction sign-off (explicit Gate 0 condition)  ✅ SIGNED OFF

> **Signed off 2026-10-03 — "yes to all".** All four statements confirmed, each against
> emitted output rather than intent:
>
> 1. **Two-layer representation.** `grep sameAs` across every emitted graph returns nothing.
>    The FHIR resource and its interpretation are distinct individuals throughout, linked only
>    by `prov:wasDerivedFrom`.
> 2. **SOLID quantity pattern.** `ex:egfr-result a sulo:Quantity ; sulo:hasValue "55.0"^^xsd:decimal ;
>    sulo:hasPart <unit> ; sulo:refersTo <quality> ; sulo:isFeatureOf <person>`, with the quality
>    `sulo:isFeatureOf` the same person.
> 3. **PRO role pattern.** `encounter sulo:hasParticipant <role>`, `role sulo:isFeatureOf <holder>`,
>    for both the patient and the clinician. No `hasPatient` or other shortcut predicate anywhere.
> 4. **The eGFR result is a reported estimate.** No measurement process, device, specimen or
>    diagnosis appears in any emitted graph.
>
> **This is the condition plan §4 names for Gate 0.** With it signed, Gate 0's stated conditions
> are met and Gates 1–4 are released from the ordering hold they have been under since they
> passed their own conditions.
>
> R8, R9 and R12 remain open. They are refinements — the practitioner's entity class, blood
> pressure profiling, and whether a participation type maps to a role class — and none is a
> Gate 0 condition. Plan §2's other sign-off requirement, "the domain typing and status
> policies", is covered by R1 and R3, both answered.

Plan Gate 0 pass condition: *"the reviewer signs off on the record/fact distinction and
PRO/SOLID target patterns."* This is a required sign-off, not a question with options.

What we are asking you to confirm:

1. **Two-layer representation** — the FHIR resource and its semantic interpretation are
   distinct individuals; no `owl:sameAs` between a FHIR resource and a person, process or
   quality; the source layer is always retained. (Concept note §1, §2.)
2. **SOLID quantity pattern** — a `sulo:Quantity` is an information object bearing
   `sulo:hasValue` and a unit part, which `sulo:refersTo` a quality that
   `sulo:isFeatureOf` its bearer. (Concept note §4; verified realisable in SULO 0.2.12.)
3. **PRO role pattern** — a process `sulo:hasParticipant` a typed role, and the role
   `sulo:isFeatureOf` its holder; no `hasPatient` or other resource-specific shortcut.
   (Concept note §6. The property chain is confirmed present in SULO 0.2.12 — DR-002.)
4. **The eGFR result is a reported estimate**, not an asserted physiological fact, and the
   map asserts no measurement process, device, specimen or diagnosis unless the source
   supports it. (Concept note §4.)

**What we need from you:** sign-off, or the specific point you want changed.

---

## R8 — Does a `Practitioner` reference mint a *person*?  ✅ R8a ANSWERED / R8b OPEN

**Blocks:** Gate 3 Encounter roles.
**R8a: ANSWERED 2026-10-03 (applied). R8b: STILL OPEN.**

- **R8a.** Is a person the right entity kind for a practitioner, or should it be an
  organisational or agent entity distinct from a patient?
- **R8b.** If someone appears as both a `Practitioner` and a `Patient` in the same source, they
  currently become **two distinct entities** — there is no merge rule. Correct, or should they
  merge, and on what evidence?

### Correction to what this item originally claimed

This section previously read "currently mints a **person** entity, the same entity kind as a
patient." **That was wrong.** `src/fhir_sulo/pipeline/services.py` read
`kind = "person" if expected_type == "Patient" else "practitioner"`, so a practitioner was
minted with entity kind `practitioner` and an IRI `practitioner-<hash>`. The reviewer was asked
to rule on behaviour the document described inaccurately. Recorded rather than quietly fixed.

### R8a — the ruling

> we need to follow ontoclean semantics here and distinguish between rigid and antirigid
> properties. the term "practitioner" refers to a role. we should mint a PractitionerRole, and
> link an individual person to an instance of that role in the process in which they are active

This identified a defect, not a preference. `entity_kind` is one of the six `key_input_fields`
for an entity IRI, so it was an **identity criterion** — and OntoClean requires identity criteria
to come from **rigid** properties. "Practitioner" is anti-rigid: a person can stop being one
without ceasing to exist. The patient side already did this correctly (`person-` IRI +
`ex:PatientRole`); the practitioner side did not.

**Applied** (DR-010):

1. `entity_kind` is now `person` for both Patient and Practitioner references.
2. An **undeclared** entity kind is now **rejected** (`ID-R10-undeclared-entity-kind`). The
   service previously slugified any kind it was handed into an IRI segment, which is how
   `practitioner-` reached an IRI without ever being declared in the identity policy.
3. `ex:ClinicianRole` → `ex:PractitionerRole`, diverging from concept note §6 on the reviewer's
   instruction. Chosen over `ClinicianRole` because `Encounter.participant.individual`
   references a `Practitioner`, so the role name is derived from what the record states rather
   than from a clinical function the source never asserted — which also leaves **R12** free to
   refine it from a reviewed participation-type table.

Practitioner entity IRIs moved (`practitioner-75edba7e…` → `person-afd67e8e…`). Patient IRIs are
unchanged. `tests/contracts/identity/test_ontoclean_rigidity.py` pins all three points.

### R8b — still open, and now the only thing keeping two people apart

`resource_type` remains a key input, so `Patient/c7` and `Practitioner/c7` are still **two
person entities**. That is defensible — `resource_type` is *record provenance*, not a claim
about the person's nature, and refusing to merge without evidence is **R2b**
(`accepted_merge_evidence` is empty by design).

But the R8a ruling sharpens this: both are now the same rigid kind, differing only by which
record they came from. **No merge rule has been reviewed, so none is implemented.** This is
not labelled answered.

---

## R9 — Blood pressure profile conformance and panel coding

**Blocks:** Gate 3 BP target shape and the pinned profile manifest.

Three connected sub-questions, all currently pinned conservatively.

### R9a — Do we claim `vitalsigns` / `bp` profile conformance?

Both are real R4 profiles (`bp` derives from `vitalsigns`, both 4.0.1). Currently the manifest
pins **base `Observation` only**, with the other two recorded as `role: "candidate"`.

Claiming `bp` conformance is not free — it **forces** `Observation.category = vital-signs`,
**requires** panel code `85354-9`, and **forbids** `Observation.value[x]` on the parent. None of
that is specified in concept note §5, so claiming it would be us inventing clinical
conformance requirements rather than implementing the note.

**Options** — **A.** stay on base `Observation`; **B.** claim `vitalsigns`; **C.** claim `bp`
and accept its three constraints.

### R9b — Does the panel code type the panel record node?

LOINC `85354-9` (blood pressure panel) is present on the parent `Observation`. Concept note §5
describes "the BP panel record" relating to both component results, but does not say whether the
panel code becomes a class assertion on that node.

**Options** — **A.** the panel code types the panel record node; **B.** the panel record stays an
untyped `ex:ObservationRecord` and the code is retained only in the source layer.

Currently **B** (the entry is marked `proposed` and types nothing), consistent with concept
note §2: "a FHIR code literal alone is not an OWL class assertion".

### R9c — The BP parent `Observation.code` is currently a placeholder

With no reviewed panel code, the parent `Observation.code` in the fixtures is `8480-6` — which
is really the *systolic* code. That is visibly wrong and is a placeholder, subsumed by R9a: if
you answer A or B above, tell us what the parent code should be; if C, it becomes `85354-9`
by profile.

---

## R10 — Is `pilot-provisional` an acceptable engineering status?  ✅ ANSWERED: A

**Blocks:** nothing yet, but decides how much of Gates 1–3 can run before you answer R1–R9.

The three pinned LOINC codes and two pinned UCUM units carry review status
**`pilot-provisional`**: interpretable, so the eGFR and BP slices can execute on synthetic data,
but every outcome reports `clinical_signoff: False` and a test fails the moment anything claims
`approved`. Nothing is marked approved anywhere.

**Options**

- **A. Accept `pilot-provisional`.** Gates 1–3 run end-to-end on synthetic data now; no output is
  ever presentable as clinically reviewed.
- **B. Reject it.** The three entries drop to `proposed`, and the entire eGFR slice becomes
  `source-only` until you have answered R1, R4 and Q-T-1 — meaning Gate 2 cannot demonstrate a
  materialized graph at all until then.

**Recommendation from engineering (not a decision):** A, because the distinction that matters —
that no output is clinically signed off — is enforced mechanically rather than by convention.

### Answer: A — accepted, 2026-09-29

The `pilot-provisional` tier is ratified. An entry at that status may be interpreted, so a map
may emit a domain class for it and Gates 2 and 3 can demonstrate a materialized graph on
synthetic data.

Recorded in `policies/code-interpretation.v1.json` under `reviewer_decisions.R10`, not only
here, so the machinery can see it. Guarded by
`tests/contracts/terminology/test_r10_provisional_tier.py`.

**What this answer explicitly did not settle**, each held by a test:

- It does **not** approve any individual typing. Whether `33914-3` means
  `RenalFiltrationQuality` is **R1b**, still open.
- It does **not** confer clinical sign-off. `clinically_signed_off_statuses` remains
  `["approved"]` alone, and every outcome from a provisional entry still reports
  `clinical_signoff: false`.
- It promotes nothing to `approved`. **Nothing is approved.**
- The `domain_namespace` is still the **R1** placeholder, so the machinery now runs end to end
  on placeholder vocabulary. "The pipeline runs" is not "the vocabulary is real".

Side effect worth recording: the policy file changed, so `policy_version` moved to
`…+sha256.50a1e206450a01e2`. **Every person IRI is byte-identical**, because keying uses a
sticky `key_revision` rather than the table's semantic version — the property Agent 5 built
and tested for exactly this. No graph migration was needed.

---

## R11 — How does a BP panel record relate to its component results?  ✅ ANSWERED

> **Answered 2026-09-30 — B, `sulo:hasPart`, plus two further relations.**
>
> *"compositionally, a record could indeed be comprised of statements, which could include the
> recording of results. This then captures where the results are located (e.g. the record).
> however, the results are information about the individual - they are features of the
> individual and they also refer to their qualities."*
>
> ```
> record  sulo:hasPart      result     # where the result is located
> result  sulo:isFeatureOf  person     # information about the individual
> result  sulo:refersTo     quality    # unchanged
> ```
>
> **Sub-question closed — it is an entailment, not a judgement call.** Whether the Encounter
> record also takes `hasPart` was sent back for a reading. It does not, and SULO 0.2.12 settles
> it twice over:
>
> - `InformationObject ⊑ (hasPart only InformationObject)` — the encounter process would have
>   to be an InformationObject, hence a Feature, hence an Object; but `Object owl:disjointWith
>   Process` and the encounter is asserted `a sulo:Process`.
> - `Object ⊑ ¬(hasPart some Process)` — the record, being an Object, cannot have a Process
>   part at all.
>
> So the Encounter record keeps `sulo:refersTo`, and the asymmetry raised under R1d is
> principled rather than accidental: **a result is information that sits inside a record; an
> encounter is an event in the world and is not located in its record.** A test derives both
> contradictions from the pinned ontology rather than restating them, so a SULO change fails
> the test instead of leaving stale prose. Nothing further needed from the reviewer unless
> they dispute the ontology.
>
> **Bears on R5.** `result isFeatureOf person` is R5's first row (materialize `isFeatureOf` on
> quantities) answered as **A**. R5's second row — an explicit unit on a `TimeInstant` —
> **remains open** and the policy stays unset.

**Blocks:** Gate 3 BP target graph.

Concept note §5 says only that "the BP panel record relates to both component results". Two
readings give different graphs:

- **A. `sulo:refersTo`** (currently emitted) — mirrors §4's record→result relation, and treats
  the panel record as an information object *about* the two results.
- **B. `sulo:hasPart`** — treats the panel as a composite whose parts are the two results.

Both are valid SULO. A is emitted because it is consistent with §4; that consistency is a guess
about intent, not a decision.

---

## R12 — Should the FHIR participation type map to a role class?

**Blocks:** Gate 3 Encounter roles, and any later resource with typed participation.

`Encounter.participant.type` carries codes such as `PPRF` (primary performer), `SBJ`, `ATND`.
Currently `PPRF` is **bound and guarded but types nothing** — the clinician role class comes
from the domain vocabulary (R1) instead, so the FHIR code is retained without being promoted to
an OWL class assertion, per §2.

**Options** — **A.** keep it source-only (current); **B.** add a reviewed participation-type
table mapping `PPRF`/`SBJ`/`ATND`/… to role classes.

If B, the table itself needs review, in the same way the code interpretation table does.

---

## Items explicitly *not* on this list

These are engineering decisions and are being made by the agents with recorded rationale,
not sent to you:

- Implementation repository (DR-001), SULO version pin (DR-002), ShEx.js build selection
  and any engine feature gaps (Agent 4, Gate 1), FHIR RDF renderer choice (Agent 2),
  identity *keying mechanism* as distinct from identity *policy* (Agent 5), graph key
  and correction mechanics (Agent 6).

Concept note §8.5 — where the runtime belongs in SULOizer, and how reviewed pairs are
published from the ShExMap Repository — is a deployment decision. It is out of scope for
Gates 0–4 and is not blocking; flag it if you want it decided sooner.
