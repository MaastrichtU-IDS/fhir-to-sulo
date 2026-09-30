# DR-008 — Domain vocabulary: mint locally now, RAG over OMOP later

**Status:** R1 answered (option A) 2026-09-30; **namespace awaiting one-token confirmation**
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

## Namespace — NOT yet applied

The reviewer nominated **`https://wi3d.org/ontostart/fhir2sulo`**.

`wi3d.org` is very likely a transposition of **`w3id.org`** — the W3C Permanent Identifier
Community Group, which is where SULO itself lives (`https://w3id.org/sulo/`). The namespace
goes into every emitted IRI and is a **graph-key input via `quality_class_iri`**, so applying
the wrong one and correcting it later is two migrations rather than one.

**Held pending a one-token confirmation.** Nothing else in this record depends on it.

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
