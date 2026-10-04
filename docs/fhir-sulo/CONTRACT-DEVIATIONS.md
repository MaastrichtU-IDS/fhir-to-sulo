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

**Corrected (DR-304): as first built, this row was not actually carried.** The linter walked
a target schema from its `start` shape. The maps put every IRI-identified target node at the
root of its own pass, so the blood-pressure target has ten root shapes and `start` names one:
SP001, SP003 and SP004 were unchecked on nine of ten BP shapes and five of six eGFR ones.
Discovery also matched only `source.shex`, so `make lint-schemas` found nothing and exited 2
on every run it ever had. `fhir_sulo.engine.maplint.lint_map` now lints once per pass declared
in the family's run-binding manifest, with that pass's staticVars in scope. All three maps
lint clean across all 25 root shapes, and fault injection into a non-`start` shape is caught.
New SP302 reports a target shape no pass reaches, because an unreachable shape is unlinted.
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

**Completed (DR-304): until now nothing outside the driver's own tests used it.** The maps
were executed by a test-only Node script that its own header said to delete when the driver
landed. That script is gone; `fhir_sulo.engine.maprun` binds once and materializes every
declared pass, and `fhir_sulo.pipeline` composes ingest, identity, terminology, the driver
and the store into one path with `python -m fhir_sulo.pipeline.cli`. Agent 3's 98 map tests
pass unchanged against it. One rule changed grain: binding coverage is checked over the union
of the passes, not per pass, because a binding the diastolic pass reads is legitimately
unconsumed by the systolic one.

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


---

## CD-5 — The engine image tag is shared mutable state across worktrees

**Reality (DR-304):** `EngineImage.ensure_built()` is a no-op when the tag exists, and every
agent worktree shares one Docker daemon. A bare version tag therefore means whoever built last
wins and everyone else runs an image that does not match their source tree. This was not
theoretical: it silently reverted the production bridge under a passing test run, twice,
during the work that found it.

**Substitute:** the tag carries a hash of the build context — `package.json`,
`package-lock.json`, `Dockerfile` and every file in `bridge/` — so it reads
`fhir-sulo/shexmap:1.0.0-alpha.33-<digest>`. Different bridges get different tags and cannot
clobber one another. `FHIR_SULO_ENGINE_IMAGE` still overrides, which is how a CI job pins a
prebuilt image.

**Effect:** none on any acceptance row; recorded because the failure mode is invisible
(a stale image runs happily and gives the wrong answer) and because any agent adding a
Docker-backed tool will hit it.

---

## CD-6 — RESOLVED by R6: the "reasoner checks consistency" row is true again

**Status:** **Resolved 2026-09-30** by the reviewer's answer to R6. Narrowed, not deleted —
what remains true is in "What is still deviant" at the end.

**Acceptance matrix row:** "PRO — Encounter target plus reasoner — *Typed roles belong to correct
holders and process; expected direct participation is inferred; no `hasPatient` predicate.*"
And concept note §7: *"an OWL reasoner checks consistency and expected PRO entailments."*

### What was wrong, and how it was found

DR-603 asserted that the reasoner catches a person wrongly typed into a `Feature` branch, "so
R6 has a safety net while it is open". Moving the Gate 3 suites onto **real map output**
(DR-605 §2) showed that claim was false for the typing the maps actually used. Measured with
HermiT on the pinned image:

| person typed as | with a Quality or Role also asserted on them |
| --- | --- |
| `sulo:SpatialObject` | **INCONSISTENT** — caught |
| `sulo:Object` — what the maps emitted | **consistent** — not caught |

`sulo:Quality ⊑ sulo:Feature ⊑ sulo:Object`, so typing a person `sulo:Object` and also typing
them into a `Feature` branch produces no clash. There was no OWL guard against a patient typed
as a Role.

### The resolution

**Review item R6 is answered: "a person is a Spatial Object."** The measurement above was the
deciding evidence. Under `sulo:SpatialObject`, `Feature owl:disjointWith SpatialObject` makes
the misclassification inconsistent, so **the OWL guard exists again and the acceptance matrix
row is true as written** for this failure mode. No wording change to the concept note or the
plan is needed; the proposed re-wording in the previous version of this deviation is withdrawn.

### Verified on real map output

Checked ahead of the map change by applying the R6 typing to the committed expected graphs
(`tests/integration/test_reasoning_pro.py::R6AppliedToRealMapOutput`):

| check | result |
| --- | --- |
| all ten emitted graphs consistent under `SpatialObject` | **yes** |
| person also typed as a Role → inconsistent | **yes — the guard works** |
| the same under bare `Object` | consistent — control still fails correctly |
| `SpatialObject ⊑ (hasPart only SpatialObject)`: any `person sulo:hasPart X`? | **none in any emitted graph** |

That last row is the axiom that could have bitten. It does not: no map asserts parthood on a
person.

The negative control `test_bare_object_does_not` is **deliberately kept** now that
`SpatialObject` is the answer. It is what shows the guard is doing work rather than being
decorative; if SULO's hierarchy ever changed so that bare `Object` also caught this, the stated
reason for the R6 answer would need revisiting, and that test would say so.

### What is still deviant

Two narrow things, neither of which was the substance of CD-6:

1. **The guard is defence in depth, not the only line.** SHACL's disjointness shapes also reject
   a node in two `Feature` branches, and they run *before* the store, so a misclassified person
   never reaches a graph either way. The OWL check is the second opinion, which is what concept
   note §7 asks it to be.
2. **The maps had not yet emitted `SpatialObject`** when this was written — Agent 3's change was
   in flight. `test_the_maps_emit_the_r6_answer` is marked `expectedFailure` and is
   self-clearing: when the maps land the answer it reports an *unexpected success*, which fails
   the suite and tells whoever landed it to remove the marker. It cannot go quietly green.

### Why the history is kept rather than deleted

A claim that was wrong, measured, and then fixed by a reviewer decision is worth more in the
record than a clean page. The measurement is also what made R6 answerable, so deleting it would
remove the evidence for the answer.


---

## CD-7 — The engine cannot re-type a time literal (and a correction to this entry)

**Origin:** the reviewer answered R5 row 2 — do not materialize a `sulo:Unit` on a time
instant — on the grounds that *"time instants are specified in the has value datatype"*. The
follow-on R5b was to emit `xsd:dateTimeStamp` where the source carries an offset and
`xsd:dateTime` where it does not, so the datatype recorded what was known. The reviewer
instructed: apply.

**It cannot be applied.** Measured against the live engine (DR-207,
`tests/contracts/maps/test_r5b_time_datatype.py`, 12 tests):

1. **The materializer re-emits the bound source term verbatim; a target constraint's declared
   datatype is ignored.**

   ```
   target declares:  sulo:hasValue xsd:dateTimeStamp %Map:{ v:effective %}
   source carries:   "2026-09-02T14:00:00Z"^^xsd:dateTime
   engine emits:     "2026-09-02T14:00:00Z"^^xsd:dateTime
   ```

   Verified for `Z`, `+01:00` and an offsetless value.

2. **Declaring it anyway is worse than a no-op.** Reverse-validating the emitted graph against
   the target schema that produced it — the §5 pivot-recovery check — *passes* when the target
   declares `xsd:dateTime` and *fails* when it declares `xsd:dateTimeStamp`. The schema would
   no longer describe its own output.

3. **ShEx datatype matching is exact, not subtype-aware**, so the source cannot read a
   `dateTime` literal as a `dateTimeStamp` either — and the source RDF is not ours to re-type:
   HL7's own published Turtle types an offset-bearing value as plain `xsd:dateTime`, and Agent
   2's renderer is validated graph-isomorphically against it.

The only remaining routes are a host-built `staticVar` literal or post-materialization
re-typing. Both are rejected: the emitted value would be one the host wrote rather than one the
map extracted, which is the line DR-302 draws.

### CORRECTION, 2026-09-30 — the second half of this entry was wrong

As first written, this deviation made two claims. The first stands; **the second was
incorrect and is withdrawn.**

It said the reviewer's reasoning was "weaker than it reads", because `xsd:dateTime` could not
distinguish a specified instant from an under-specified one. That rested on a premise **I
supplied when proposing R5b**: that FHIR `dateTime` legitimately permits a clock time with no
offset. It does not. FHIR R4's published regex places the timezone group *inside* the `T`
group and does not make it optional:

```
2026-09-02                 valid    -> renders xsd:date; not an instant (DR-009)
2026-09-02T14:00:00        INVALID  -> cannot occur in conformant R4
2026-09-02T14:00:00Z       valid
2026-09-02T14:00:00+01:00  valid
```

Verified against `StructureDefinition/dateTime` in HL7's published R4 definitions, and
independently by the lead.

**So the reviewer was right.** Every conformant value that renders `xsd:dateTime` carries an
offset; anything coarser renders `xsd:date`, `gYearMonth` or `gYear`, is not an instant, and is
`source-only` under DR-009. There is no under-specified instant for the datatype to fail to
distinguish. *"Time instants are specified in the has value datatype"* holds.

Asserted on emitted output rather than left as an argument:
`tests/contracts/maps/test_every_emitted_instant_carries_an_offset.py` checks every emitted
`xsd:dateTime` for an offset, checks no `xsd:date` reaches the semantic layer, and re-checks
the R4 regex so that if FHIR ever relaxed it, the test says which decisions need revisiting.

### What actually remains deviant

**Only finding 1: the engine cannot re-type.** A target declaring `xsd:dateTimeStamp` still
emits `xsd:dateTime`, and declaring it breaks reverse validation.

This is now **inert rather than limiting.** Because every instant carries an offset,
`xsd:dateTimeStamp` would have been *unconditionally* correct — R5b's conditional had no
reachable second branch. So the engine limitation costs us a more precise datatype, not a
distinction: the offset is present in the literal either way, and the graph is correct as
emitted.

**R5c is withdrawn.** It asked how to treat an offsetless instant. There are none.

R5 row 2's answer stands unchanged: no `sulo:Unit` on any time node.
### A side effect worth knowing

rdflib canonicalises the two datatypes differently: `…T14:00:00Z` is rewritten to
`…T14:00:00+00:00` under `xsd:dateTime` but survives untouched under `xsd:dateTimeStamp`. An
explicit `+01:00` is untouched either way. So had both datatypes been emitted, the same instant
would have had different lexical forms depending on its type, and the SHACL graph digests would
have followed. Pinned by a test.
