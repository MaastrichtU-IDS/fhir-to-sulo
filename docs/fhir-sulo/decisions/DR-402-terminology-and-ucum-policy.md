# DR-402 — Terminology and UCUM resolution: pinned snapshot and explicit outcomes

**Status:** Decided (engineering) + **Review requested** (every interpretation)
**Date:** 2026-09-29
**Gate:** 1 (deterministic mock terminology service) / 2 (eGFR slice)
**Owner:** Agent 5 — identity and terminology
**Implements:** concept note §2 ("a FHIR code literal alone is not an OWL class
assertion"), §3 (an external lookup must supply a value or fail explicitly), §4
(failure variants); plan §2 (Agent 5 row), §4 Gate 1, §5 (row "Status/absence"),
§7 (risk row "Observation code is treated as an unconditional fact or class")

## 1. The published interface

```python
from fhir_sulo.terminology import TerminologyService, Coding, UnitRef

term = TerminologyService()                 # loads policies/, asserts offline
code = term.resolve_code(Coding(system, code, display=None), expected_kind=None)
unit = term.resolve_unit(UnitRef(system, code, display=None), expected_dimension=None)
term.policy_versions                        # dict for the RunRecord
```

Outcome unions, all carrying `.source` (the original system and code), `.record`
(a `DecisionRecord`) and `.status` in the `TransformResult` vocabulary:

| Type | `.status` | Extra |
| --- | --- | --- |
| `CodeInterpreted` | `mapped` | `.interpretation` → `result_class`, `quality_class`, `observation_kind`, `expected_unit_dimension`, `review_status`, `clinical_signoff` |
| `CodeSourceOnly` | `source-only` | `.reason_code`, `.reason`. **No class attribute at all.** |
| `CodeRejected` | `rejected` | `.reason_code`, `.reason` |
| `UnitResolved` | `mapped` | `.unit` → `unit_id`, `ucum_code`, `unit_iri`, `dimension`, `review_status`, `clinical_signoff`, `converted` |
| `UnitSourceOnly` | `source-only` | `.reason_code`, `.reason` |
| `UnitRejected` | `rejected` | `.reason_code`, `.reason` |

`.source_retained()` returns the source system, code and display on **every** outcome,
including rejections.

## 2. Deterministic and offline

Gate 1 asks Agent 5 for "a deterministic mock terminology/identity service". This one
reads only the pinned JSON snapshot in `policies/`. There is no HTTP client in the
package; `TerminologyService.__init__` calls `assert_offline()`, which raises if a policy
table ever sets `live_lookup_at_runtime`, and a test fails the build if `requests`,
`urllib`, `http.client`, `socket` or `httpx` is imported anywhere under
`src/fhir_sulo/`. The snapshot was hand-pinned offline from the concept note's worked
examples; no network call happens at build time either.

Pinned scope, exactly as Gate 0 fixed it:

| System | Code | Result class | Unit dimension |
| --- | --- | --- | --- |
| LOINC | `33914-3` | `ex:EGFRResult` | `egfr-rate` |
| LOINC | `8480-6` | `ex:SystolicBloodPressureResult` | `pressure` |
| LOINC | `8462-4` | `ex:DiastolicBloodPressureResult` | `pressure` |

| UCUM code | Dimension | Unit IRI |
| --- | --- | --- |
| `mL/min/{1.73_m2}` | `egfr-rate` | `ex:ucum-mL-min-1_73_m2` |
| `mm[Hg]` | `pressure` | `ex:ucum-mm_Hg` |

A test asserts the interpretable set is *exactly* this, so accidental widening fails.
The unit IRI local names deliberately match the concept note's schematic graph.

## 3. A code becomes a class only through a reviewed entry

There is no path from a code literal to a domain class except an entry in
`policies/code-interpretation.v1.json`. Enforcement:

- `CodeSourceOnly` and `CodeRejected` have **no** `result_class`, `quality_class`,
  `domain_class` or `interpretation` field. Reaching for one raises
  `TerminologyUnavailable`, not `None`. A test asserts the dataclass field set.
- An unknown code in a known system → `source-only` (`unknown-code`).
  An unknown code system → `source-only` (`unknown-code-system`).
  An entry whose `review_status` is not interpretable → `source-only`.
  An entry marked `rejected`, or an incomplete `Coding` → `rejected`.
  The policy's own defaults are validated to be one of `source-only` / `rejected`, and a
  value outside that set raises rather than falling through.
- `defaults.silent_pass_through` and `defaults.invent_class_for_unknown_code` are `false`
  and asserted false by a test.
- The source system and code are recorded on the outcome *and* in the audit record for
  all three statuses.

`expected_kind` lets a map guard say "I expect a quantitative observable here"; a
mismatch is an explicit `observation-kind-mismatch` source-only outcome, not a silent
pass.

Note on the Gate 2 "wrong code" negative fixture: an off-scope code coming out of this
service is `source-only` (retained, typed nowhere). It is the *map's* code guard that
must then reject the eGFR shape. Terminology's job is to refuse to type it, not to
decide the map's eligibility.

### Review status, and why anything is interpretable at all

Nothing is `approved`. The reviewer has signed nothing off. To let Gates 1-3 run on
synthetic data without pretending otherwise, the three pinned codes and two pinned units
carry `review_status: "pilot-provisional"` — interpretable, but every resulting outcome
reports `clinical_signoff: False`, and that flag rides in the audit record for Agent 6 to
put in the `RunRecord`. A test fails the moment any entry claims `approved`, so a
reviewer sign-off cannot slip in unnoticed.

## 4. UCUM: no silent normalisation

`defaults.conversion` is `disabled` and `silent_normalisation` is `false`.

| Situation | Outcome | Reason code |
| --- | --- | --- |
| Pinned code, dimension matches | `mapped` | — |
| No unit code | `rejected` | `missing-unit-code` |
| Unit system is not UCUM | `rejected` | `unknown-unit-system` |
| UCUM code not in the snapshot | `rejected` | `unknown-unit-code` |
| Known code, wrong dimension | `rejected` | `unit-dimension-mismatch` |
| Known code, not interpretable status (e.g. `kPa`) | `rejected` | `unit-not-approved` |

Rejecting rather than source-only follows concept note §4 directly: "missing or
unrecognized UCUM units fail this numeric target shape", and §2's rule against claiming
an unqualified numeric result. `kPa` is in the table on purpose, at `proposed`, so that a
dimensionally-compatible but unapproved unit has a *recorded* outcome instead of falling
through the unknown branch — and so the "do not convert silently" rule has something to
be tested against.

**The resolver does not parse UCUM grammar.** It matches pinned literal codes. A
syntactically valid variant such as `mL/min/(1.73.m2)` is `unknown-unit-code`, not a
guess. Adding real UCUM expression parsing would be a new dependency and a new decision
record; it is not needed for the pinned scope.

The FHIR `Quantity.unit` display text (`"mL/min/1.73 m2"`) is kept in the source layer
only and is never treated as the unit; a test asserts `ucum_code != source.display`.

## 5. Versioning

Every table has a semantic `version`. For `RunRecord` there are two single strings:

- `PolicyBundle.policy_version` —
  `fhir-sulo-policies/identity-1.0.0+code-1.0.0+unit-1.0.0+sha256.6b2c35b7a7c69f3f`.
  One field covering all three tables, resolvable with `parse_policy_version()` and
  checkable with `bundle.matches_policy_version()`.
- `PolicyBundle.terminology_snapshot` — `pilot-pinned-subset-2026-09-29`. The code and
  UCUM snapshots are collapsed into one string while they agree, and reported as
  `code=…+ucum=…` if they ever diverge.

`PolicyBundle.versions` keeps the per-table detail and rides in every `DecisionRecord`.
`python -m fhir_sulo.policy.report` renders all three tables as Markdown for a reviewer;
the JSON stays the only source of truth.

## 6. Test evidence

```
$ .venv/bin/python -m pytest tests/contracts -q
122 passed in 0.54s
```

Terminology-specific coverage: each pinned code maps to its reviewed class and reports
`clinical_signoff: False`; unknown code, unknown system, SNOMED (recognised, no entries)
and the `proposed` BP panel code each take their declared `source-only` path; incomplete
`Coding` is rejected; the source system/code/display survive on all four outcome kinds;
non-interpreted outcomes have no class attribute and raise on access; the three statuses
exercised together cover exactly `{mapped, source-only, rejected}`; every UCUM failure
mode above is asserted individually; no outcome ever reports `converted: True`; and the
code table's `expected_unit_dimension` values are checked against the unit table's
declared dimensions so the two tables cannot drift.

## 7. Questions for the reviewer

**Q-T-1 — approve or correct the three domain typings.** `33914-3 → ex:EGFRResult` with
quality `ex:RenalFiltrationQuality`; `8480-6 → ex:SystolicBloodPressureResult` with
`ex:SystolicBloodPressureQuality`; `8462-4 → ex:DiastolicBloodPressureResult` with
`ex:DiastolicBloodPressureQuality`. These names are Agent 5's transcription of the
concept note's worked examples, not a reviewed ontology commitment, and the concept note
is explicit that the eGFR value is a *reported estimate* rather than an asserted
physiological fact. Note DR-002 Q1: the concept note types the referent `sulo:Feature`,
but `sulo:Feature` is a disjoint union of four branches, so the quality classes above
presumably need `sulo:Quality` as their SULO parent. Confirm.

**Q-T-2 — the blood-pressure panel code `85354-9`.** Should the panel code type the BP
panel record node, or does the panel stay an untyped `ex:ObservationRecord` with only its
two components typed? Currently `proposed`, so it yields `source-only` and types nothing.

**Q-T-3 — unknown UCUM code: rejected or source-only?** Current default is `rejected`,
following concept note §4 literally. The alternative is to treat it like
`dataAbsentReason`: keep the observation record, emit no numeric quantity, and mark it
`source-only`. These produce visibly different graphs for the same input, so the reviewer
should choose rather than the default standing by accident.

**Q-T-4 — should the pilot ever convert units?** Currently never: `kPa` where `mm[Hg]` is
expected is rejected rather than converted. Converting would introduce a derived value
that is not in the source, which cuts against the concept note's retention rules, but it
is a legitimate clinical convenience. Current answer: conversion disabled.

**Q-T-5 — is `pilot-provisional` an acceptable engineering status?** It lets Gates 1-3
run on synthetic data while every outcome carries `clinical_signoff: False`. If the
reviewer would rather nothing be interpretable before sign-off, say so and the three
entries drop to `proposed`, which makes the whole eGFR slice `source-only` until review.

---

## Addendum — 2026-10-03: quality-mode migration cost, measured

The lead asked whether the IR-602/IR-604 work makes the R2 quality-mode switch easier or its
cost more visible. It makes the cost **measurable**, which it was not before.

The fingerprint harness built to verify IR-602 computes every quality IRI across the whole
fixture set under **both** modes. Over the 114 (fixture, reference slot, observable code)
triples in `fixtures/r4/`:

| | distinct quality nodes |
| --- | ---: |
| `per-observation` (the current provisional answer) | **93** |
| `persistent-per-person-code` | **27** |

A 3.4x collapse, and **100% of quality IRIs move if the mode flips** — all 114, by
construction, because the two modes key on different input sets (6 fields vs 9).

This corroborates the lead's amendment measurement mechanically. An amendment that adds only an
`Observation.note` mints a new quality individual under `per-observation` because the key
includes `source_resource_version_id`; under `persistent-per-person-code` it cannot, because
the version is not in the key at all.

Two things follow, neither of which changes the mode — R2's answer is the reviewer's and stays
`per-observation`:

1. **Switching is a re-key of every quality node, not a config tweak.** It needs a golden-graph
   regeneration and a store correction pass, so it should be scheduled, not slipped in.
2. **The reviewer now has a number.** When R2 is revisited, "does one quality per event or one
   per person-and-code match the intended theory" can be asked against 93 vs 27 nodes for this
   fixture set, rather than in the abstract.

The caveat in `policies/identity-policy.v1.json` stands unchanged, and the test that fails if
it is dropped still passes. This addendum records evidence; it does not settle the question.
