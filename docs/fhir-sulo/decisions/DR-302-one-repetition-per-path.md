# DR-302 — One repetition per path, and resource-rooted maps

**Status:** Decided (architectural constraint on all schema pairs)
**Date:** 2026-09-29
**Gate:** 1 → binds Gates 2, 3, 4 and 5
**Depends on:** DR-301 blocker B1

## The constraint

> **Every ShExMap source/target pair may contain at most one repeating triple constraint on
> any single path from the root, and every map is rooted at exactly one FHIR resource.**

Enforced mechanically by the schema-pair linter (DR-301 decision 3), which fails the build
rather than relying on authors to remember. Agents 3 and 6 must design to it from the start.

## Why

DR-301 B1: at two levels of repetition the engine silently mis-associates groups and drops
members. It is not a tunable limit — `normalizeBindingTree` discards outer-group boundaries by
design, and upstream ships a conformant fixture that *expects* the flattened output. There is no
version of this engine, and no flag, that makes a two-level map correct.

## Why our scope fits inside it

> **Corrected 2026-09-29.** This table previously claimed BP and Encounter were depth 1.
> They are not, in the schemas that actually shipped. An independent review caught it. The
> corrected figures are below, and the consequence — that no production map exercises
> iteration scopes at all — is stated rather than left implicit.

| Map | Repetition depth *as shipped* | Why |
| --- | --- | --- |
| eGFR `Observation` → SOLID quantity | **0** | a single `valueQuantity` |
| BP `Observation` → two component quantities | **0** | two *non-repeating* max-1 constraints on `Observation.component`, each pinned to its own LOINC code (`8480-6`, `8462-4`) |
| `Encounter` → PRO roles | **0** | `Encounter.participant` is cardinality **1** in v1 (DR-201 §5.1) |

### What this means, stated plainly

**Iteration scopes — the mechanism concept note §3 names as the answer to repetition — are
never exercised by a production map.** Every shipped pair is depth 0.

The acceptance condition "two BP panels preserve their component pairing" is therefore
satisfied *structurally* rather than by the engine's repetition handling: the two panels are
two separate `Observation` resources and so two separate engine runs, and within a panel the
systolic and diastolic values are told apart by LOINC code rather than by position in a
repetition. That is a **stronger** guarantee than relying on iteration scopes — 80 is bound by
the `8462-4` constraint whatever `fhir:index` says, which is why the reordered-serialisation
fixture passes — but it is a different guarantee from the one the plan's risk row anticipated.

Two honest consequences:

1. The plan's repetition risk ("repeated components lose association") is **side-stepped, not
   demonstrated**. The engine's one-level repetition handling is proven by probe 3 in
   `tools/engine/probes/`, on a synthetic pair — not by any map we ship.
2. `Encounter.participant` at cardinality 1 means **"who participated in this encounter" only
   answers for single-clinician encounters.** A second participant fails source validation
   loudly rather than silently, which is the right failure, but it is a real scope limit and it
   is recorded in DR-201 §5.1 and DR-007's debt table.

The constraint in this decision record still binds: a future map that *does* repeat must
contain at most one repeating constraint on a path, and the linter enforces it across every
root shape of every pass.

The concept note's §5 case — "two blood-pressure panels" — is **two `Observation` resources**,
not one nested structure. Mapped resource-by-resource, each run sees one level, and the
within-panel association the acceptance matrix demands is preserved because the two panels never
share a binding context at all. This is why probe 3 passes with the exact required multiset
`{(bp-1,120,80),(bp-2,105,70)}`.

The constraint therefore costs us nothing in Gates 0–4. It is recorded because it is a real
limit that **will** bite later: a `Bundle`-rooted or `Patient`-rooted map is ≥2 levels and would
silently emit a wrong graph. Gate 5's `MedicationAdministration` must be checked against it
before that work starts.

## The decomposition, if depth is ever needed

Verified working (DR-301 probe 10, PASS — reproduces a two-level map exactly):

1. Bind the repeated group's **own source IRI** in the source schema, with a Map variable on the
   shape-valued constraint (`%Map:{ v:reportIri %}`).
2. **Pass A** emits those IRIs as leaves. They are the join key.
3. **Pass B** materializes each group *rooted at its own IRI* (`-r`), one engine invocation per
   group.
4. Union the passes, relabelling blank nodes per pass so `_:tm0` collisions cannot merge
   unrelated nodes.

Side benefit: it gives every repeated group a stable target IRI, recovering most of what the
absent `id()` would have provided.

## Why this is not hiding an engine failure in a postprocessor

The instruction is explicit: engine gaps get a reproducer and a concrete resolution, not a
postprocessor; and target triple construction stays in the ShExMap schemas. This decomposition
satisfies both, and the distinction is worth stating precisely because it is easy to blur.

- **Every emitted triple comes from a ShExMap target schema.** The host emits none and rewrites
  none. If you delete the schemas, the pipeline produces nothing.
- **The join key is bound by the schema**, not inferred by the host. The host reads a variable
  the map declared; it does not guess which panel a value belonged to.
- **The host's actions are ones the contract already assigns it.** Concept note §3 gives the host
  map selection, batching, named-graph versioning and identity. Choosing a root node and
  unioning named graphs is squarely inside that boundary.
- **We never run the broken configuration.** The linter refuses a two-level pair at build time,
  so there is no wrong output to repair.

What *would* be rule-hiding, and is prohibited here: running the two-level map, observing the
flattened result, and re-associating panels host-side by matching values or positions. That
would move a graph-construction rule out of the schema and into code, and it would be guessing.
It is not what this does.

## Consequences

- Agent 3 authors one pair per resource type; no pair may nest repetitions.
- Agent 6's driver loop iterates resources and, where needed, groups; it is a **driver**, not a
  transformer, and its tests must assert that it emits no triple of its own.
- The linter is a Gate 1 deliverable and gates every later gate.
- Gate 5 must re-check `MedicationAdministration` and any Bundle-level ambition against this.
