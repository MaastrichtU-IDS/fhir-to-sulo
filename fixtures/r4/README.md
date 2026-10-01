# `fixtures/r4/` — synthetic FHIR, canonical RDF, expected pivot bindings

Owner: Agent 2 (FHIR ingestion). Consumed by Agent 3's maps, Agent 4's engine
probes and Agent 6's QA.

**All pilot data here is synthetic.** The only exception is
`_oracle/`, which holds HL7's own published R4 examples and is used solely to
check that our renderer reproduces HL7's Turtle (DR-101). Nothing in `_oracle/`
is pilot input.

Format and rationale: [DR-102](../../docs/fhir-sulo/decisions/DR-102-fixtures-and-binding-tuples.md).

## Layout

```
fixtures/r4/<family>/<fixture-id>/
    <resource-id>.json        hand-authored synthetic FHIR R4 resource (1..n)
    case.json                 what the case is for; declared eligibility and reference outcomes
    expected-bindings.json    expected pivot bindings with their repetition structure
    canonical.nt              GENERATED  canonical rendered RDF (sorted N-Triples)  <- consume this
    readable.ttl              GENERATED  the same graph, nested Turtle, for humans
    <variant>.nt              GENERATED  extra RDF a case.json declares
```

Regenerate the derived files:

```bash
python3 fixtures/r4/build.py           # write
python3 fixtures/r4/build.py --check   # verify; exit 1 on drift (also a unit test)
```

## Which file to consume

`canonical.nt`. It is sorted, duplicate-free N-Triples with deterministic blank
node labels, so a diff is a content diff. `readable.ttl` is the same graph and
is for review only — the test suite proves the two are isomorphic.

Blank node labels in a multi-resource fixture are prefixed with the source file
name (`bp-1-b7`), so two panels can never share a node by accident.

## Inventory

**eGFR** (concept note §4) — 15 cases: `egfr-baseline`,
`egfr-data-absent-reason`, `egfr-comparator`, `egfr-unit-missing`,
`egfr-unit-unrecognised`, `egfr-code-unmapped`, `egfr-reference-unresolvable`,
`egfr-reference-ambiguous`, `egfr-entered-in-error`, `egfr-contained-subject`,
`egfr-corrected`, `egfr-amended`, `egfr-retracted`,
`egfr-effective-date-only`, `egfr-preliminary`.

Four of those — `egfr-baseline`, `egfr-corrected`, `egfr-amended`,
`egfr-retracted` — are **the same resource at versions 1 to 4**: final 55.0,
corrected 58.5, amended (a note added, no value change), entered-in-error.
Same resource id `egfr-456`, same canonical URL, different `meta.versionId`
and different source digest.
That is the lineage Gate 4's correction row needs; `egfr-entered-in-error` is
a *different* resource and cannot supply it. All four source files are called
`egfr-456.json`, one per directory, because the file is named after the
resource it holds. See DR-102 §3 and
`tests/contracts/ingest/test_version_lineage.py`.

**Blood pressure** (concept note §5) — 5 cases, each two separate `Observation`
resources: `bp-two-panels` (the baseline `{(bp-1,120,80),(bp-2,105,70)}`),
`bp-component-omitted`, `bp-reordered-serialisation`, `bp-duplicate-values`,
`bp-other-patient`.

**Encounter** (concept note §6) — 4 cases: `enc-baseline`, `enc-in-progress`,
`enc-open-period`, `enc-contained-practitioner`.

DR-102 §3 has the full table with each case's declared outcome.

## Two things to know before writing a map against these

**No Bundles.** Every BP panel is its own `Observation`, independently
renderable and independently rootable, because the pinned engine supports one
repeating constraint per path and roots every map at a single FHIR resource
(Agent 4, DR-302).

**The person is not in the graph.** `expected-bindings.json` lists
`identity_provided_variables` — `person`, and for Encounter also `clinician`.
Those come from the identity service as run bindings (concept note §4). Binding
a person straight from `subjectRef` is the record/fact error §2 forbids.

## Expected bindings, in one example

```json
{ "scope": "panel",
  "variables": ["panel", "sys", "dia"],
  "expected_multiset": [["bp-1","120","80"], ["bp-2","105","70"]],
  "must_not_contain": [["bp-1","120","70"], ["bp-2","105","80"]] }
```

Load `binding_tree` with `fhir_sulo.ingest.load_binding_tree` to get a
`fhir_sulo.contracts.BindingNode`, then compare
`tree.tuples_for_scope("panel", ["panel","sys","dia"])` as a sorted list — not
a set, because `bp-duplicate-values` has two panels with identical values that
must stay two tuples.

A missing variable binds `""`. An omitted BP component therefore gives
`("bp-1","120","")`, never `("bp-1","120","70")`.

Variables marked `"datatype": true` bind `lexical^^datatype`, so
`55.0^^...#decimal` and `2026-09-02T14:00:00Z^^...#dateTime`. Precision is part
of the asserted tuple.

`extraction` is a small declarative path spec that recovers the same tuples
from `canonical.nt`; `tests/contracts/ingest/test_bindings.py` requires the
declared and extracted multisets to agree for every fixture, so the expected
tuples are checked rather than merely asserted.

## Adding a fixture

1. Write the resource JSON and a `case.json` declaring the expected outcome.
2. Write `expected-bindings.json`, including an `extraction` spec.
3. `python3 fixtures/r4/build.py`.
4. `make contracts`.

If the renderer refuses your resource with
`element X is not in the pinned element table`, that is working as intended:
widen `profiles/fhir-r4-element-table.json` deliberately rather than letting
the element be dropped.
