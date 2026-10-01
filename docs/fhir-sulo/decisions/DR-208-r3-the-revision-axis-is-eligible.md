# DR-208 — R3: `amended` and `corrected` are eligible, because status has two axes

**Status:** Applied to the maps. **One thing outstanding:**
`profiles/fhir-r4-pilot.json` still says `source-only`, so the two artefacts
disagree and a test says so until they do not.
**Date:** 2026-10-01
**Gate:** 2 / 3, and it unblocks Gate 4's correction row
**Owner:** Agent 3 — mapping author
**Answered by:** the human clinical/ontology reviewer, relayed by the integration lead

## The answer, and why it is not a loosening

FHIR's `Observation.status` conflates two independent axes:

| axis | values |
| --- | --- |
| **verification** | `registered` → `preliminary` → `final` |
| **revision** | `final` → `amended` / `corrected` |

A position on the revision axis is *post-final* and has been revisited, so it
does not reduce reliability. Holding `amended` and `corrected` at
`source-only` applied the verification axis's caution to a position on the
revision axis.

That had a concrete cost, and it is the part worth remembering: **a correction
never reached the semantic layer.** v2 replaced v1's graph and then asserted
nothing, so the erroneous value was removed and the corrected one never
arrived. The store ended up with less truth than before the correction.

Still **not** eligible, and this is the point of the answer rather than a
leftover: `preliminary` and `registered` *are* verification states, and
`entered-in-error` is a retraction rather than a revision.

## Applied

| artefact | change |
| --- | --- |
| `maps/r4/egfr/egfr-source.v1.shex` | status value set `["final"]` → `["final" "amended" "corrected"]` |
| `maps/r4/bp/bp-source.v1.shex` | same |
| both `MapContract`s | `status_eligibility` widened, with the two-axis reasoning recorded |
| `maps/r4/encounter/*` | **unchanged.** R3's answer is about Observation revision statuses; Encounter's value set has no revision axis. Note added so the omission is deliberate rather than overlooked. |

Pairing hashes recomputed. No expected graph changed, because every fixture
still carries `final`.

## The tests assert the distinction, not the widening

Widening a guard is exactly the change where "status `final` maps" keeps
passing while the new statuses are silently broken. So both directions:

- `amended` and `corrected` **map**, and produce a graph **identical** to the
  one `final` produces — the revision axis changes that the record was
  revisited, not what is asserted. If `amended` emitted a different shape, the
  widening would be doing more than the answer licensed.
- `preliminary`, `registered`, `entered-in-error`, `cancelled` and `unknown`
  **still do not map**, and emit nothing.
- the status is **bound but never emitted** in any case: §2 keeps the record's
  status in the source layer.

A suite asserting only the first bullet would stay green with the new statuses
broken; one asserting only the first two would stay green with the guard
removed entirely.

Evidence is currently a **labelled perturbation** of `egfr-baseline`'s
rendered RDF, because `egfr-corrected` still carries `final`. Agent 2 is
re-pointing it to `corrected`;
`TheCorrectedFixtureExercisesTheNewStatus` **skips** until that lands and then
becomes the real evidence, with the perturbation as corroboration. It skips
rather than fails because the fixture is Agent 2's to change and the
behaviour is already covered.

## The consequence the reviewer accepted, asserted rather than described

Amend only a `source_only` element — say `Observation.issued` — and the new
version's semantic triples are **identical** to its predecessor's, on the
**same node IRIs**. The graph key still moves, because `source_json_digest` is
a content field, so the store reports a **replacement** rather than
"unchanged".

That is visible rather than silent, and it is the same shape as DR-601's
engine-upgrade case. `AnAmendmentToASourceOnlyElementStillReplaces` asserts
all of it, including the part that matters most: **the digest must
distinguish the two versions.** If such an amendment ever reported
*unchanged*, the amendment would have gone unrecorded — that is the failure
worth catching, and it is the only one of these assertions whose inversion is
dangerous rather than merely surprising.

## Outstanding: two artefacts disagree about what is eligible

`profiles/fhir-r4-pilot.json :: status_policy.Observation` still says
`amended: source-only`. The maps now enforce `final`, `amended`, `corrected`.
One of them is wrong, and until they agree the graph is produced under a rule
that two reviewed artefacts describe differently.

`TheProfileAndTheMapsAgreeAboutEligibility` fails until they match. Clearing
it is a two-line edit to `status_policy.Observation` plus the `note` beside
it, which currently reads *"When R3 is answered, this block is the single
place to change."* If the relay was wrong, the guards revert instead.

This is the same pattern as DR-206's reviewer-decision gap, which was closed
the same way. The maps move when the reviewer answers; the record has to catch
up, and a red test is how it does not get forgotten.

## Explicitly left alone

A **`finished` Encounter with an open-ended period** still needs a ruling, and
no fixture fabricates one. `Encounter.period` keeps both endpoints required,
so `enc-open-period` stays `source-only`.
