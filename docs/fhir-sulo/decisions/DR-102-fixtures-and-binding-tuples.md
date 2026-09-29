# DR-102 — Fixture layout and the expected-binding-tuple format

**Status:** Decided (layout and format) + **Review requested** (three interpretation questions)
**Date:** 2026-09-29
**Gate:** 0
**Owner:** Agent 2 (FHIR ingestion). **Consumed by:** Agent 3 (maps), Agent 4 (engine), Agent 6 (QA).

## 1. Fixture layout

One directory per case under `fixtures/r4/<family>/<fixture-id>/`.

| File | Authored by | Purpose |
| --- | --- | --- |
| `<resource-id>.json` | hand | the synthetic FHIR resource. One or more per case. |
| `case.json` | hand | what this case is for, and the **declared** eligibility outcome, reason fragments and reference outcomes. |
| `expected-bindings.json` | hand | the expected pivot bindings with their repetition structure (§2). |
| `canonical.nt` | generated | canonical rendered RDF: sorted N-Triples. **This is the artifact to consume.** |
| `readable.ttl` | generated | the same graph as nested Turtle, for human review only. |
| named variants | generated | extra RDF files a `case.json` declares, e.g. `canonical-reordered.nt`. |

Generated files carry a "do not hand-edit" banner and are produced by
`python3 fixtures/r4/build.py`. `--check` re-renders and fails on drift, and a
unit test runs it, so a renderer change cannot silently invalidate the fixtures.

All data is synthetic. The only non-synthetic files are HL7's own published R4
examples under `fixtures/r4/_oracle/`, which exist solely as a rendering oracle
for DR-101 and are never pilot input.

**Every BP panel is its own `Observation` resource.** Per Agent 4's DR-302, the
pinned engine supports one repeating constraint per path and every map is
rooted at a single FHIR resource, so no Bundle-rooted fixture is produced.

## 2. Expected-binding format

`format: "fhir-sulo/expected-bindings/0.1.0"`. Three parts, each with a job.

### `binding_tree`

A serialisation of `fhir_sulo.contracts.BindingNode`. Load it with
`fhir_sulo.ingest.load_binding_tree(doc)` and the acceptance check is the call
the frozen interface already offers:

```python
tree.tuples_for_scope("panel", ["panel", "sys", "dia"])
```

This is deliberately the same call `tests/contracts/test_interfaces.py`
demonstrates, so Agent 3 and Agent 4 compare against the artifact with no
adapter in between.

### `assertions.scope_tuples`

Per repetition scope: `variables` (the tuple order), `expected_multiset`, and
`must_not_contain`.

For `bp-two-panels` the required answer is present literally:

```json
{ "scope": "panel",
  "variables": ["panel", "sys", "dia"],
  "expected_multiset": [["bp-1","120","80"], ["bp-2","105","70"]],
  "must_not_contain": [["bp-1","120","70"], ["bp-2","105","80"],
                       ["bp-1","105","80"], ["bp-2","120","70"]] }
```

`must_not_contain` holds the exact cross-join the concept note names. The test
compares **sorted lists**, not sets, so two panels with identical values
(`bp-duplicate-values`) cannot coalesce into one. A missing variable binds the
empty string, so an omitted BP component leaves a hole — `("bp-1","120","")` —
rather than borrowing its neighbour's value.

Why a multiset comparison rather than "every value appears": the cross-join
`{(bp-1,120,70),(bp-2,105,80)}` contains exactly the same *set of values* as the
correct answer. `test_a_membership_check_would_not_have_caught_the_cross_join`
asserts that, so the reason for the stricter comparison is in the suite.

### `extraction`

A small declarative path spec that recovers the same tuples **from the rendered
RDF**. Without it, `expected_multiset` would be an unchecked assertion about a
graph nobody looked at. With it, `test_bindings.py` requires the declared
tuples and the extracted tuples to agree for every fixture.

The language is intentionally tiny — a step is either `{"p": "<predicate local
name>"}` or `{"filter": {"steps": [...], "equals": "..."}}` — because it is
evidence, not an engine. It is **not** a second mapping library: it selects and
compares, it never constructs a target triple. Plan §1's prohibition on a
second library of ad hoc FHIR-to-SULO rules is about target construction; this
does none.

Two properties worth stating:

* **Components are selected by LOINC code, not by position.** The
  `bp-reordered-serialisation` case proves it: `canonical-components-reversed.nt`
  is a *different graph* (the `fhir:index` values move) yet yields the same
  tuples.
* **A variable that binds more than once inside its scope is an error**, not a
  silent pick. Two systolic components in one panel would hide a cross-join, so
  the extractor raises.

### Datatypes in tuples

Variables marked `"datatype": true` bind `lexical^^datatype`, e.g.
`55.0^^http://www.w3.org/2001/XMLSchema#decimal` and
`2026-09-02T14:00:00Z^^http://www.w3.org/2001/XMLSchema#dateTime`. Precision is
therefore part of the asserted tuple: a decimal rendered as `55` or a dateTime
downgraded to a date changes the multiset. The eGFR fixture lists both of those
in `must_not_contain`.

### What is *not* in the tuples

`egfr:person` and the encounter's person/clinician are listed under
`identity_provided_variables`, not extracted. They are the identity service's
output supplied as a run binding (concept note §4), and no amount of reading the
FHIR RDF produces them. Any consumer that binds a person from `subjectRef`
directly has made the record/fact error §2 forbids.

## 3. Fixture inventory

**eGFR (concept note §4)** — 10 cases, one per line, each its own directory:

| Fixture | What it is | Declared outcome |
| --- | --- | --- |
| `egfr-baseline` | §4 verbatim: `egfr-456`, final, LOINC 33914-3, 55.0 `mL/min/{1.73_m2}`, `Patient/p123`, 2026-09-02T14:00:00Z | eligible |
| `egfr-data-absent-reason` | `dataAbsentReason` instead of a value | source-only |
| `egfr-comparator` | `valueQuantity.comparator = "<"` | rejected |
| `egfr-unit-missing` | display text only, no UCUM system/code | rejected |
| `egfr-unit-unrecognised` | UCUM `mL/min`, well-formed but not pinned | rejected |
| `egfr-code-unmapped` | LOINC 48642-3, real but not pinned | rejected |
| `egfr-reference-unresolvable` | `subject` = `#nobody`, dangling | rejected |
| `egfr-reference-ambiguous` | two contained Patients share id `p` | rejected |
| `egfr-entered-in-error` | `status = entered-in-error` | source-only |
| `egfr-contained-subject` | `subject` = `#p-inline`, resolves | eligible |

**Blood pressure (concept note §5)** — 5 cases, each two `Observation`s:

| Fixture | What it is |
| --- | --- |
| `bp-two-panels` | the baseline: `bp-1` 09:00 120/80, `bp-2` 10:00 105/70, `mm[Hg]`, same patient |
| `bp-component-omitted` | `bp-1` has no diastolic component |
| `bp-reordered-serialisation` | same graph in a different line order, **and** a component-array reversal that legitimately changes `fhir:index` |
| `bp-duplicate-values` | `bp-3` and `bp-4` both 120/80 at different times |
| `bp-other-patient` | `bp-5` (200/110) belongs to `Patient/p999` |

**Encounter (concept note §6)** — 4 cases:

| Fixture | What it is | Declared outcome |
| --- | --- | --- |
| `enc-baseline` | §6 verbatim: `enc-9`, finished, `Patient/p123`, `Practitioner/c7`, 14:00→14:30 UTC | eligible |
| `enc-in-progress` | `in-progress` with a bounded period | source-only |
| `enc-open-period` | open-ended period: `Period.start` only, no end triple emitted | source-only |
| `enc-contained-practitioner` | `participant.individual` = `#pr-inline`, contained | eligible |

## 4. Questions for the reviewer

Submitted to Agent 1 for consolidation into
`docs/fhir-sulo/REVIEW-REQUEST.md` (which currently holds R1–R7; these are
additional, and Agent 1 owns that file). None has been resolved unilaterally;
engineering proceeds against the concept note's literal text with the policy
parameterised in `profiles/fhir-r4-pilot.json`, so a reviewer answer is a
manifest edit and not a re-authoring.

Q-A2-3 below interacts with R5 (closed-world shape strictness): an unknown
endpoint that must be preserved is exactly the case where a closed-world target
shape and SULO's open-world existentials pull in opposite directions.

### Q-A2-1 — Should the pilot claim `vitalsigns` / `bp` profile conformance?

R4 publishes `http://hl7.org/fhir/StructureDefinition/vitalsigns` and
`http://hl7.org/fhir/StructureDefinition/bp` (both version 4.0.1; `bp` derives
from `vitalsigns`). Plan Gate 0 says "select the R4 profile set", and concept
note §5 cites HL7's blood-pressure example, which *does* declare `vitalsigns`.

But claiming them changes the fixtures. `bp` requires
`Observation.category = vital-signs`, requires the panel code **85354-9**, and
forbids `Observation.value[x]` on the parent. Concept note §5 specifies none of
that — it names only the component codes 8480-6 and 8462-4.

Currently pinned: base `Observation` only, with `vitalsigns` and `bp` recorded
in the manifest as `role: "candidate"`. **Question: should the pilot assert
conformance to `vitalsigns`/`bp` for the BP family, and if so, may the fixtures
gain `category` and the 85354-9 panel code?**

Related and smaller: the BP fixtures currently carry `Observation.code` =
8480-6 (the systolic code) on the parent, because §5 gives no panel code. If
the answer to the above is yes, that becomes 85354-9.

### Q-A2-2 — What is the eligibility of an `in-progress` Encounter?

Concept note §6: *"An `in-progress` Encounter may receive a separate, explicitly
defined policy; it is not treated as a finished interval."* That says what it is
not. Currently pinned as **source-only**, which is the conservative reading.
**Question: confirm source-only, or define the separate policy.** If a policy is
wanted, the open question is whether an in-progress encounter should materialise
a `sulo:Process` with a `sulo:StartTime` and no `sulo:EndTime`, which touches
DR-002's Q2/Q3 about closed-world target shapes.

### Q-A2-3 — May a `finished` Encounter have an open-ended period?

The brief asks for an "open-ended period (no end)" variant. Pairing that with
`status = finished` produces a resource that is clinically incoherent (finished,
but with no end time) while being perfectly valid FHIR — `Encounter.period` is
0..1 and `Period.end` is 0..1. The fixture `enc-open-period` therefore pairs the
open period with `in-progress` rather than fabricating a finished-with-no-end
resource. **Question: is a finished Encounter with no `period.end` a case the
pilot must handle, and if so, is it source-only, rejected, or materialised with
an unknown endpoint?** Concept note §2 requires preserving unknown endpoints,
which suggests it should be representable rather than rejected.

### Q-A2-4 (minor, for the record) — `Observation.code` on a BP panel

Not a question so much as a flag: with no reviewed panel code, the BP fixtures'
parent `Observation.code` is 8480-6, which is really the systolic component
code. That is a placeholder chosen to keep the code-eligibility rule exercised.
It is subsumed by Q-A2-1 and will be corrected by whatever the reviewer decides.
