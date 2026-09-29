# DR-205 — Tolerated source-only elements, and the one conflict over `method`

**Status:** Decided (engineering), with **one conflict referred to the reviewer**
**Date:** 2026-09-29
**Gate:** 2 / 3
**Owner:** Agent 3 — mapping author
**Found by:** Agent 2, while adding the `egfr-456` version-lineage fixtures
**Depends on:** concept note §2, `profiles/fhir-r4-pilot.json` `source_only_elements`

## The defect

Every source schema is `CLOSED`, so an element it does not list makes
`shex-validate` exit 1. The shapes listed only `fhir:DomainResource.contained`,
so **any Observation carrying `fhir:Observation.issued` failed source
validation**. Agent 2 bisected it:

| variant | result |
| --- | --- |
| `issued` + `meta.lastUpdated` | `stage=validate, ok=false` |
| `meta.lastUpdated` only | `stage=done` |
| `issued` only | `stage=validate, ok=false` |
| neither | `stage=done` |

`meta.lastUpdated` slipped through only because the nested `Meta` shape is not
closed — which is luck, not design.

This is worse than a missing fixture field, because `issued` is ordinary: it
appears on HL7's published `observation-example-f205-egfr`, the example
concept note §4 is modelled on.

*One correction to how this was reported to me:* that oracle would have been
rejected by these shapes anyway — it carries `method` and has no top-level
`valueQuantity`, only components. `fixtures/r4/_oracle/` is a renderer oracle
(DR-101) and never pilot input. The `issued` gap is real and is fixed; the
"we would reject the very example the pilot is built on" framing overstates
it slightly, and the overstatement is worth not propagating.

## What is now tolerated

Each source schema lists the elements `profiles/fhir-r4-pilot.json` declares
`source_only`, with the **wildcard `.` value expression** and no Map variable:

```shex
  fhir:Observation.issued . * ;
```

Three properties follow, and they are what make this safe:

- **Nothing binds.** No Map variable sits on any of them, so none can reach
  the target graph. `test_time_semantics.py` asserts that for `issued` and
  `meta.lastUpdated` specifically.
- **Depth stays 1.** A wildcard has no sub-shape, so a repeating tolerated
  element cannot create the second level of repetition the engine mis-maps
  (DR-302).
- **The set cannot drift.** `test_repeating_constraints_are_the_declared_source_only_elements`
  requires every tolerated wildcard to be an element the pinned profile
  declares source-only, so the CLOSED shapes cannot be widened by accident.

Observation (eGFR and BP): `text`, `contained`, `identifier`, `issued`,
`performer`, `interpretation`, `note`, `bodySite`, `specimen`, `device`, and
`component.interpretation`. Encounter: `text`, `contained`, `identifier`,
`type`, `serviceProvider`, and `participant.period`.

## The conflict: `Observation.method`

`profiles/fhir-r4-pilot.json` lists `Observation.method` under
`source_only_elements`. Concept note §2 says:

> Never drop a comparator, absent-value reason, **method**, unit code/system,
> component association, or a modifier extension **while claiming an
> unqualified numeric result**.

These cannot both be honoured. "Retained in the source layer" is not the same
as "not dropped": the semantic layer would still assert a bare
`sulo:Quantity` with a value and a unit, as if nothing qualified it. A
creatinine-based and a cystatin-C-based eGFR are not the same measurement, and
the difference is exactly what `method` carries.

**Held at REJECT.** An Observation carrying `method` fails source validation
and produces no semantic output. That is the conservative side — `source-only`
rather than a wrong assertion — and it is the side §2 names explicitly.
`test_method_is_not_tolerated` and
`MethodIsNotSilentlyDropped::test_an_observation_carrying_a_method_is_rejected`
hold it there.

**Referred to the reviewer**, as item **N4** for the consolidated request:

> `Observation.method` is declared `source_only` in the pinned profile but
> named in concept note §2 as something that must not be dropped while
> claiming an unqualified numeric result. Either the profile entry is wrong,
> or §2 means "retained in the source layer" by "not dropped". If the latter,
> the fix is one line in each Observation source schema. If the former, the
> pilot needs a reviewed method-qualified quantity pattern — which is the same
> pattern R3 already needs for `valueQuantity.comparator`, and the two should
> be answered together.

Not resolved here, and not resolved by whichever document was read last.

`Observation.valueString` and `.valueCodeableConcept` are also left out, for a
different and uncontroversial reason: a resource carrying one *instead* of
`valueQuantity` already fails because `valueQuantity` is required, and one
carrying *both* is invalid FHIR and should fail rather than have the string
silently dropped.

## The §2 time distinction is now tested

§2 asks us to distinguish `effective[x]` (clinically relevant),
`issued` (availability) and `meta.lastUpdated` (version update). Until the
shape tolerated `issued` we could not accept a resource carrying all three, so
the distinction was untested on the map side. `test_time_semantics.py` now
asserts, on the emitted graph: the resource validates, neither `issued` nor
`lastUpdated` is bound to any variable, only `effective[x]` reaches
`sulo:TimeInstant`, the graph is otherwise byte-identical with and without the
extra times, and the lineage IRI names `meta.versionId` rather than any
timestamp.

Its inputs are `egfr-baseline`'s rendered RDF with the extra time triples
appended **by the test** — a labelled perturbation, not a fixture. A real
fixture carrying all three times would be better evidence and belongs to
Agent 2; raised.

## Consequence for Gate 4 that the version fixtures made testable

With `egfr-456` now at v1/v2/v3, the map-side half of the correction row can
be asserted rather than claimed: the result, record and time node IRIs are
**identical** across v1 and v2, so v2's triples replace v1's on the same nodes,
which is what "a correction removes stale derived assertions" (§7) requires.
Only the value and the `prov:wasDerivedFrom` version IRI move.
`CorrectionReplacesTheSameNodes` in `test_egfr_gate2.py` asserts it, and also
records a consequence for **R2**: under `per-observation` the quality IRI moves
with the version, so a correction mints a new quality node while the quantity
keeps its IRI; under `persistent-per-person-code` it does not. Whoever answers
R2 should see that rather than discover it.

## Noted, not changed

Agent 2 could not give the corrected v2 `status: "corrected"`, because the
source shapes guard status to `["final"]` while R3 holds `amended`/`corrected`
open. That is the intended behaviour and stays. It should be revisited when R3
is answered, and `status_eligibility` in each `MapContract` is where the answer
lands.
