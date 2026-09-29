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

**Built (DR-303):** `tools/shexmap-lint` / `fhir_sulo.engine.linter`. Error codes SP001
(unbound), SP002 (nested repetition), SP003 (unknown Map function *and* undeclared prefix),
plus SP004–SP007 for the other silent-deletion paths. Exit 1 on any error; no downgrade flag.
Negative schemas live in `tests/engine/schemas/neg-*`, and `TestTheLinterIsNotCryingWolf`
checks each one against the live engine, so every refusal is backed by the misbehaviour it
prevents rather than by assertion.

One correction to the row's wording as written above: **SP003 covers two routes, not one.**
The engine matches its variable pattern before its function pattern, so `id(v:code)` is read
as a variable in an undeclared prefix `id(v` and never reaches the function dispatcher at all,
while `skolemize(x)` does and throws `Unknown extension`. Both end in silent shape deletion.
A checker that only looked for `name(...)` would miss the case the row is actually named after.

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

**Built (DR-303):** `fhir_sulo.engine.driver`. Guards are set explicitly on every call and
`run-pass.js` refuses a request that omits one, so an engine default cannot leak in. Each
silent failure raises: `UnboundVariables`, `ExplorationTruncated`, `AcceptCeilingReached`,
`BindingsNotConsumed`, `SourceValidationFailure`, `UntracedQuad`.

**One finding that changes how the two tools are read:** `BindingsNotConsumed` is not
redundant with the unbound-variable check. The no-colon route of CD-1 leaves
`lastReport.unboundVariables` **empty**, so binding coverage is the only runtime signal that a
shape was deleted. Conversely, nested repetition (CD-3, DR-302) trips *none* of the driver's
checks — every binding is consumed and nothing is truncated; the values are simply attached to
the wrong groups. The linter and the driver each catch what the other cannot.

---

## CD-3 — `MedicationAdministration` and Bundle-level mapping are unvalidated against DR-302

**Scope:** Gate 5 only; not blocking Gates 0–4.

A `Bundle`-rooted or `Patient`-rooted map is ≥2 levels of repetition and would silently emit a
wrong graph (DR-301 B1). Gate 5 must re-check its resource shapes against DR-302 before starting,
and budget for the decomposition if depth is genuinely required.


---

## CD-4 — Lineage reaches the binding tree, not the source triple

**Acceptance matrix row:** "Lineage — *every quad traces to a source binding or constant plus
source resource version, map hash, and run activity*."

**Reality (DR-301 probe 5):** the engine gives, per emitted quad, the target-schema
`TripleConstraint` that produced it and the Map variable and binding-tree frame it consumed
(`materializer.provenance`), plus the path of each binding back into the binding tree
(`frameOrigins`). It does **not** give the source triple. `ShExUtil.valToExtension` discards
the `TestedTriple` structure on the way from the validation result to the binding tree.

**Substitute:** `QuadLineage` is populated with what the engine actually knows — the
constraint, the variable, the iteration key — and the per-run parts (`source_version_id`,
`pairing_hash`, run activity) come from `RunRecord` as the contract already intends. Quad →
constraint → variable → binding-tree position is complete and machine-readable today.

**What is not yet covered:** quad → *source triple*. Recovering it means joining
`frameOrigins` paths against the `.val` document, which does retain `TestedTriple`
subject/predicate/object, and `shex-validate --provenance` can additionally attach source
character ranges. This is integration work, not a missing engine capability.

**Effect on the row:** the row is met for "traces to a source binding". If an auditor needs
"traces to the source *triple*", that is a named, scoped piece of work and not a property the
current pipeline has. Recorded rather than glossed, because the two readings are easy to
conflate and only one of them is true today.
