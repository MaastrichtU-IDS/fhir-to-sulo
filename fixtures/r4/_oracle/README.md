# Renderer oracle — HL7-published R4 examples

**These are not pilot data.** They are six files published by HL7 as part of the FHIR R4
specification, vendored here so the renderer conformance test is offline and reproducible.
No fixture in the pilot is derived from them, and nothing here is synthetic patient data of
ours.

## What they are for

`tests/contracts/ingest/test_oracle_conformance.py` renders each `.json` with our pinned
renderer and compares the result **graph-isomorphically** to HL7's own `.ttl` for the same
example. This is what stops the renderer being self-certified: agreement is with an external
authority, not with our own expectations.

The three examples are exactly the ones the concept note cites:

| File | Concept note | Result |
| --- | --- | --- |
| `observation-example-f205-egfr` | §4 (eGFR / SOLID) | isomorphic, 151 triples |
| `observation-example-bloodpressure` | §5 (BP components) | isomorphic, 168 triples |
| `encounter-example` | §6 (Encounter / PRO) | isomorphic, 22 triples |

The suite carries a control (`test_the_comparison_can_fail`) asserting that a deliberately
mismatched pair is **not** isomorphic, so a passing run cannot be vacuous.

## Two documented deviations

Both are renderer options, **default off**, enabled only for this comparison:

1. HL7 emits `a loinc:33914-3` class arcs. We do not, because concept note §2 forbids treating
   a FHIR code literal as an OWL class assertion. Emitting them here only proves we *can*
   reproduce HL7's graph; the pilot's canonical output omits them.
2. HL7 emits an `owl:Ontology` header pointing at `build.fhir.org`. Not meaningful for us.

## Provenance and licence

Source: the HL7 FHIR R4 (4.0.1) specification, `https://hl7.org/fhir/R4/`.
HL7 publishes the FHIR specification content, including these examples, under the
**Creative Commons CC0 1.0 Universal Public Domain Dedication**. FHIR® is a registered
trademark of Health Level Seven International; its use here is descriptive and implies no
endorsement.

Retrieved 2026-09-29. Do not edit these files — they are an external oracle. If an upstream
change is ever needed, re-retrieve and record the date here, because silently editing an oracle
turns the conformance test into a tautology.
