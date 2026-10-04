# DR-008 — Domain vocabulary: mint locally now, RAG over OMOP later

**Status:** R1 answered (option A) and namespace applied, 2026-09-30
**Gate:** 0

## The answer

**R1 = A.** Mint a small project-local domain vocabulary, as subclasses of the SULO classes
verified in DR-002.

### Why B was withdrawn as offered

The review request offered "reuse the `sulo2snomed` / `sulo2sphn` mappings already in
`AIDAVA-DEV/sulo/mapping/`". Having read both files, that option was overstated and the
reviewer should not be held to the version they were shown:

| File | Mappings | What it actually gives |
| --- | ---: | --- |
| `sulo2snomed.ttl` | 25 | SNOMED's **top-level hierarchies** only — `\|Clinical finding\| ⊑ sulo:Process`, `\|Observable entity\| ⊑ sulo:InformationObject`. Nothing for a specific observable. |
| `sulo2sphn.ttl` | 51 | Does include `sphn#BloodPressure` — but **`⊑ sulo:InformationObject`**. |

**Neither file contains a single mapping to `sulo:Quality`.** Zero, across both.

That is not a gap to fill later; it is a modelling disagreement. SPHN types blood pressure as
an `InformationObject`, which in the concept note's SOLID pattern is the **quantity**'s role.
§4 wants the quality to be a `Feature` branch that the quantity `refersTo` and that
`isFeatureOf` the person. Binding to SPHN would collapse the two layers the pattern exists to
separate, and would answer **R4** as "InformationObject" — contradicting §4.

## The 12 classes minted

```
RenalFiltrationQuality   SystolicBloodPressureQuality   DiastolicBloodPressureQuality
EGFRResult               SystolicBloodPressureResult    DiastolicBloodPressureResult
ObservationRecord        EncounterRecord                ClinicalEncounter
PatientRole              ClinicianRole                  Person
```

All reachable from one indirection point (`domain_namespace` plus the per-code `result_class`
and `quality_class`), which a test enforces by swapping the whole vocabulary and requiring no
schema to change.

## Namespace — applied

**`https://w3id.org/ontostart/fhir2sulo/`**

The reviewer first wrote `wi3d.org`. That was queried before applying rather than after,
because the namespace is a **graph-key input via `quality_class_iri`** and correcting it later
would have been a second migration. Confirmed as `w3id.org` — the W3C Permanent Identifier
group, where SULO itself lives at `https://w3id.org/sulo/`.

A trailing slash was added, matching SULO's own form.

### What the re-key actually moved

Applied across 46 files. The two contract documents — the concept note and the implementation
plan — were **deliberately left alone**: their `ex:` examples are illustrative, and editing
them would make the acceptance contract track the implementation rather than constrain it.

Measured on `egfr-baseline`, before and after:

| | before | after |
| --- | --- | --- |
| quality IRI | `…/quality-16ec875da7a23e14…` | `…/quality-2f1a2b367d5c6b15…` |
| person IRI | `…/person-144658abc676816c…` | `…/person-144658abc676816c…` |

**The quality hash changed; the person hash did not.** That is the predicted behaviour
confirmed rather than assumed: `quality_class_iri` is a quality-key input and moved with the
namespace, while person keying does not include the domain vocabulary at all. 431 lines changed
in the expected graphs, all of them either the prefix substitution or the quality re-key.

This was the migration R1 and R2 were warned to cost. Answering them together meant paying it
once.

## The successor: RAG over OMOP vocabularies

The reviewer's stated direction, recorded so the local vocabulary is understood as interim
rather than an end state:

> eventually, we should replace this with a RAG over OMOP vocabularies with LLM reranking to
> find best matches, following what we have previously done

Precedent cited was a `voidx harvest` run against a SPARQL endpoint producing Turtle plus a
JSONL log and a local store. The pattern — harvest an endpoint into a pinned local artifact
with a provenance log, then query it offline — matches what this pilot already does for the
terminology snapshot and the SULO pin, so the two should converge rather than diverge.

**Out of scope for Gates 0–4** and not blocking. Two properties this pilot should keep so the
successor can drop in:

1. The vocabulary stays behind the single indirection point, so swapping the source of a
   domain class is a policy change and not a re-authoring.
2. A code-to-class binding stays a **reviewed table entry** with a `review_status`. An LLM
   reranker proposes; it does not approve. Concept note §2 — "a code-to-class interpretation
   needs a reviewed terminology rule" — applies to a machine proposer exactly as it does to a
   human transcription, and arguably more so.

## R1b — what the LOINC code denotes

Answered 2026-09-30: *"we want to capture the quality and the measurement result. the loinc
code specifically pertains to the measurement result."*

The table already carried both `result_class` and `quality_class` per entry, so no structural
change was needed. What was missing was a statement of **which one the code means**; a
top-level `code_denotes: "result_class"` now says it, so nothing downstream can read
`quality_class` as the code's denotation.

| code | `result_class` (what the code denotes) | `quality_class` (separate commitment) |
| --- | --- | --- |
| `33914-3` | `EGFRResult` | `RenalFiltrationQuality` |
| `8480-6` | `SystolicBloodPressureResult` | `SystolicBloodPressureQuality` |
| `8462-4` | `DiastolicBloodPressureResult` | `DiastolicBloodPressureQuality` |

*Correction to the record:* an earlier summary to the reviewer displayed `domain_class: null`
for these entries. There is no `domain_class` field — the query named one that does not exist,
and the real `result_class` was populated all along. The reviewer's answer may have been
formed against that mistaken display; it happens to confirm what was already there.

## R1d — is a record an information object that refers to the event?

The reviewer asked: *"A record would have attributes consistent with an information object,
and not the actual encounter → a record `sulo:refersTo` a particular event. is that the case?"*

**Yes.** Verified against the emitted graph, not the intent:

```turtle
ex:encounter-record-enc-9 a ex:EncounterRecord, sulo:InformationObject ;
    sulo:refersTo    ex:encounter-enc-9 ;        # the ClinicalEncounter process
    prov:wasDerivedFrom <https://fhir.example/Encounter/enc-9/_history/1> .
```

One asymmetry worth the reviewer's eye, since it was not asked about: the **Observation**
record refersTo the **result** (a Quantity), while the **Encounter** record refersTo the
**event** (a Process).

```turtle
ex:egfr-record-egfr-456 a ex:ObservationRecord, sulo:InformationObject ;
    sulo:refersTo ex:egfr-result-egfr-456 .      # a Quantity, not a process
```

Both follow their respective sections (§4 and §6) and both are defensible, but they are
different relations wearing one predicate. This is the same question **R11** asks about the BP
panel record, and the answers should probably be given together.

---

## Addendum — 2026-10-03: `ClinicianRole` → `PractitionerRole` (DR-010)

The table above is left as written; this records the one class that has since been renamed.

`ClinicianRole` is now **`PractitionerRole`**, on the reviewer's OntoClean ruling answering R8a.
The count is unchanged at 12.

The rename is not cosmetic in one respect: it accompanied removing `practitioner` as an *entity
kind*. An entity kind is a key input for an entity IRI, so it was acting as an identity
criterion, and OntoClean requires those to be rigid. The role now carries the anti-rigid term
and the person does not. See [DR-010](DR-010-ontoclean-practitioner-is-a-role.md).

`PractitionerRole` rather than keeping `ClinicianRole` because
`Encounter.participant.individual` references a `Practitioner`, so the name is derived from
what the record states rather than from a clinical function the source never asserted.

This also diverges from concept note §6, which writes `ex:ClinicianRole` and
`ex:clinician-role-enc-9`. The divergence is reviewer-ordered and is flagged in
`maps/r4/encounter/encounter-bindings.v1.json`, whose other local names still match §6 exactly.


---

## Addendum — 2026-10-03: a 13th class, `PrimaryPerformerRole` (DR-013)

R12 was answered "both": the encounter-scoped role node carries `ex:PractitionerRole` **and**
`ex:PrimaryPerformerRole`. The count goes from 12 to **13**.

Unlike the other twelve, this one is not bound from the manifest's static vocabulary alone. It
comes from a reviewed table, `policies/participation-type-interpretation.v1.json`, keyed on the
`Encounter.participant.type` code the resource actually carries — so it is the first domain
class in this pilot derived from a **coded clinical statement** rather than from a position in a
schema or a FHIR resource type. See [DR-013](DR-013-r12-participation-type-types-the-role.md).
