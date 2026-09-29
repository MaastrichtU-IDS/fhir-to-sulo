# DR-202 — Expected target graphs, negative outcomes, and where each one is decided

**Status:** Decided (engineering)
**Date:** 2026-09-29
**Gate:** 2 / 3
**Owner:** Agent 3 — ShExMap mapping author
**Consumes:** Agent 2's 19 fixtures and their declared outcomes (DR-102 §3)

`fixtures/expected/` holds one directory per Agent 2 fixture: an `outcome.json`, and a
`target.nt` for the nine that materialize. `fixtures/expected/build.py --check` re-runs every
map and fails on drift; `tests/contracts/maps/test_expected_graphs.py` runs it.

## The outcome matrix

**All 19 agree with Agent 2's independently declared eligibility. No disagreements.**

| Fixture | Agent 2 | Map outcome | Decided by | Triples |
| --- | --- | --- | --- | ---: |
| `egfr-baseline` | eligible | mapped | — | 21 |
| `egfr-contained-subject` | eligible | mapped | — | 21 |
| `egfr-entered-in-error` | source-only | source-shape-nonconformant | `Observation.status` value set `["final"]` | 0 |
| `egfr-data-absent-reason` | source-only | source-shape-nonconformant | `Observation.valueQuantity` required | 0 |
| `egfr-comparator` | rejected | source-shape-nonconformant | `sh:EGFRQuantity` is CLOSED, no `Quantity.comparator` | 0 |
| `egfr-unit-missing` | rejected | source-shape-nonconformant | `Quantity.system` and `.code` required | 0 |
| `egfr-unit-unrecognised` | rejected | source-shape-nonconformant | UCUM value set `["mL/min/{1.73_m2}"]` | 0 |
| `egfr-code-unmapped` | rejected | source-shape-nonconformant | LOINC value set `["33914-3"]` | 0 |
| `egfr-reference-unresolvable` | rejected | identity-rejected | identity service `ID-R2-no-candidate` | 0 |
| `egfr-reference-ambiguous` | rejected | identity-rejected | host declines to claim an entity | 0 |
| `bp-two-panels` | eligible | mapped | — | 64 |
| `bp-component-omitted` | eligible | mapped | — | 52 |
| `bp-reordered-serialisation` | eligible | mapped | — | 64 |
| `bp-duplicate-values` | eligible | mapped | — | 64 |
| `bp-other-patient` | eligible | mapped | — | 66 |
| `enc-baseline` | eligible | mapped | — | 29 |
| `enc-contained-practitioner` | eligible | mapped | — | 29 |
| `enc-in-progress` | source-only | source-shape-nonconformant | `Encounter.status` value set `["finished"]` | 0 |
| `enc-open-period` | source-only | source-shape-nonconformant | `Period.end` required | 0 |

## Three things the matrix is careful about

**`source-only` and `rejected` are not distinguished by the map, and should not be.** Both
produce no target graph. The distinction is an *eligibility* verdict and it belongs to Agent 2's
`EligibilityEvaluator` and Agent 5's policy tables, which is where `case.json` records it. The
map's job is to emit nothing, loudly, with a parseable diagnostic — which every negative row
does. `outcome.json` records both verdicts side by side so the agreement is visible rather than
assumed.

**Two negatives are decided *after* the source shape passes.** `egfr-reference-unresolvable`
and `egfr-reference-ambiguous` are conformant Observations; what fails is identity. The host
builds the identity request from Agent 2's resolved reference and **fabricates no candidate
evidence**: an unresolvable reference yields zero candidates and the identity service's own
`ID-R2-no-candidate` rejection, and an ambiguous one is refused before a request is made,
because no reviewed merge rule exists (concept note §2, and the frozen
`ResolvedReference.require_entity_iri` contract). An earlier version of the harness invented a
single candidate and both fixtures wrongly materialized 21 triples; that is the mistake this
paragraph exists to prevent recurring.

**Every negative carries a diagnostic.** `outcome.json.diagnostic` holds either the element
paths and violation types a `shex-validate` `Failure` blames, or the identity rejection's
reason code. A silent rejection would be the same failure class DR-301 warns about.

## Why the golden graphs are not the acceptance conditions

`target.nt` is generated and then reviewed. It is regression evidence: it catches drift, and it
catches a change in another agent's component, because it contains the identity service's
literal entity and quality IRIs.

The acceptance conditions are hand-written invariants in `test_egfr_gate2.py`,
`test_bp_gate3.py`, `test_encounter_gate3.py` and `test_inverse_pivot.py`, none of which read
`fixtures/expected/`. A wrong graph regenerated into `target.nt` still fails them. Six
fault-injections were run to verify that; all six were caught, and each by the specific guard
meant for it (DR-201 and the Gate 2/3 report).

## Run parameters the graphs depend on

Recorded in every `outcome.json` under `run_parameters`, because they are unanswered review
items and the graphs are not valid without them:

- `quality_identity_mode: "per-observation"`. The shipped default is unset and **rejects every
  request** (R2). It is set explicitly so a graph exists at all. Answering R2 moves every
  quality IRI in every `target.nt` and nothing else — asserted in
  `test_egfr_gate2.py::test_the_two_quality_modes_give_different_quality_iris`.
- The domain vocabulary is the `https://example.org/fhir-sulo/` placeholder, which has no owner
  (R1). Answering R1 also moves every quality IRI, because `quality_class_iri` is a quality key
  input.
- Every code and unit used carries `review_status: pilot-provisional` and
  `clinical_signoff: false` (R10). No output here is presentable as clinically reviewed.

## Regenerating

```bash
python3 fixtures/expected/build.py           # write
python3 fixtures/expected/build.py --check   # verify; exit 1 on drift
```

Both need Docker and the pinned engine image; `tests/contracts/maps/` skips with an explicit
message where Docker is unavailable, and a skip there is not a pass.
