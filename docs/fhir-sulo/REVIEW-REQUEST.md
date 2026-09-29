# Consolidated review request — clinical and ontology interpretations

**Status:** OPEN — awaiting the human clinical/ontology reviewer
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

## R1 — The domain vocabulary is a placeholder and needs an owner

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

**Meanwhile:** target shapes are authored against SULO upper-level terms only, with domain
typing emitted through a single indirection point so the vocabulary can be swapped.

---

## R2 — Quality identity: does a quality persist across observations?

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

## R3 — Status and `value[x]` interpretation policy

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
| `finished` Encounter *with* an open-ended period | **open** — valid FHIR, clinically incoherent. No fixture fabricates this; say whether it should be rejected or represented. | not specified |

**What we need from you:** an outcome for every **open** row, and confirmation of the proposed
ones. The comparator row additionally needs a modelling answer, not just an outcome.

**Meanwhile:** every open row is held at `rejected` with an explicit diagnostic naming this
item, so no unqualified assertion can escape while the question is open.

---

## R4 — `sulo:Quality` vs bare `sulo:Feature` for the observed quality

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

**What we need from you:** A or B.

---

## R5 — Closed-world shape strictness vs SULO's open-world existentials

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

## R6 — Person typing and the `Feature` / `SpatialObject` disjointness

**Blocks:** Gate 2, Gate 3 reasoning checks. Depends on R1.

`sulo:Feature owl:disjointWith sulo:SpatialObject`, and `sulo:Feature rdfs:subClassOf sulo:Object`.
So the class chosen for a patient determines whether the graph stays consistent: a patient
typed as a `sulo:SpatialObject` can bear features, but must never itself be typed as any
`Feature` branch.

The concept note writes `ex:person-p123 a ex:Person` without saying where `ex:Person` sits
under SULO.

**What we need from you:** the SULO parent for the patient/practitioner class —
`sulo:SpatialObject`, bare `sulo:Object`, or something else. (This is the specific form R1
takes for the person class, and Gate 3's reasoner check depends on it.)

---

## R7 — Record/fact distinction sign-off (explicit Gate 0 condition)

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

## R8 — Does a `Practitioner` reference mint a *person*?

**Blocks:** Gate 3 Encounter roles.

`Encounter.participant.individual = Practitioner/c7` currently mints a **person** entity, the
same entity kind as a patient. Two sub-questions:

- **R8a.** Is a person the right entity kind for a practitioner, or should it be an
  organisational or agent entity distinct from a patient?
- **R8b.** If someone appears as both a `Practitioner` and a `Patient` in the same source, they
  currently become **two distinct entities** — there is no merge rule. Correct, or should they
  merge, and on what evidence?

Concept note §6 types the clinician role holder as `ex:clinician-c7` without saying what it is.
Interacts with **R1** and **R6**.

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

## R10 — Is `pilot-provisional` an acceptable engineering status?

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
