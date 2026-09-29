# Contract deviations

Places where the pinned toolchain cannot satisfy the acceptance contract as literally written,
with the substitute and its justification. Kept separate from `REVIEW-REQUEST.md`, which is for
clinical and ontology interpretation only. These are engineering deviations, recorded for
visibility rather than sign-off — but they change acceptance rows, so they are not buried in a
decision record.

---

## CD-1 — The acceptance matrix references `id()`, which the pinned engine does not have

**Acceptance matrix row:** "Mapping analysis — Static schema check and negative schemas —
*Unbound variables, incompatible repetition scopes, and invalid `id()` uses fail before data
processing.*"

**Reality (DR-301, probe 4b):** `shex@1.0.0-alpha.33` ships no `id()` Map function. Only
`hashmap`, `regex` and `test` exist. Worse, an unknown Map function does not error — it
*silently prunes the entire shape that used it*. Only the root node's IRI is controllable.
No static checker ships at all; `--diagnose` crashes non-TTY with exit 99.

**Substitute:**

1. **Node identity** comes from the per-group source IRIs produced by the DR-302 decomposition,
   with blank nodes accepted below them. This is checked by node-key rules declared in
   `MapContract.node_key_rules` rather than by an engine function.
2. **Static analysis** is performed by the host-side schema-pair linter (DR-301 decision 3),
   which must cover the row's three obligations: unbound variables, incompatible repetition
   scopes (the DR-302 rule), and — replacing "invalid `id()` uses" — **any unknown Map function**,
   precisely because the engine's response to one is silent shape deletion.

**Effect on the row:** the obligation is unchanged in substance; the mechanism moves from the
engine to a named, tested host tool. The row should be read as "invalid node-key or unknown Map
function uses fail before data processing".

**Not weakened:** the linter must fail the build, not warn.

---

## CD-2 — The shipped CLI is banned; the API is the only supported entry point

**Acceptance matrix row:** "Deployability — *One documented command runs CLI/API and CI tests
with pinned versions*."

**Reality (DR-301, blockers B2 and B3):** `shexmap-materialize` silently truncates every
repetition to 19 items, exits 0 on fatal errors, and exits 0 on partial output with an empty
stderr.

**Substitute:** the documented command drives `ThreadedMaterializer` through the programmatic
API via the host-side materialization driver, with `maxAccepts`/`maxRepeat`/`maxSteps`/
`exploreSteps` set explicitly and fail-fast on `MaterializationError`, non-empty
`lastReport.unboundVariables`, `explorationTruncated`, and bindings-not-fully-consumed.

**Effect on the row:** none in substance — there is still one documented command. The row's
"CLI" refers to *our* CLI, which is satisfied; the *engine's* CLI is an implementation detail
and is unusable.

---

## CD-3 — `MedicationAdministration` and Bundle-level mapping are unvalidated against DR-302

**Scope:** Gate 5 only; not blocking Gates 0–4.

A `Bundle`-rooted or `Patient`-rooted map is ≥2 levels of repetition and would silently emit a
wrong graph (DR-301 B1). Gate 5 must re-check its resource shapes against DR-302 before starting,
and budget for the decomposition if depth is genuinely required.
