# DR-304 — The composed pipeline, and linting a map instead of a shape

**Status:** Decided and implemented
**Date:** 2026-09-29
**Gate:** 1 → unblocks Gates 2, 3 and 4
**Fixes:** integration review blockers B1 and B2
**Supersedes:** DR-303's schema-layout claim
**Owner:** Agent 4

## B2 — the linter had never analysed a production map

Two faults, and the second is the one that mattered.

**Discovery matched nothing.** `tools/shexmap-lint` looked for files literally
named `source.shex` and `target.shex`. The maps ship as
`maps/r4/<family>/<family>-source.v1.shex`. So `make lint-schemas` found no
pairs and exited 2 on every run it has ever had, including the CI step added on
the strength of it. DR-303's layout claim was wrong; the maps were not.
Discovery now lives in `fhir_sulo.pipeline.manifest.discover`, follows what is
on disk, and is shared with the runner so the two cannot drift.

**The linter walked from `start` only.** This is the substantive fault. The
maps put every IRI-identified target node at the root of its own pass, because
the engine has no `id()` and only a materialization's root has a controllable
IRI (DR-301 4b/4c, DR-302). The blood-pressure target therefore declares ten
root shapes and `start` names one. SP001, SP003 and SP004 — CD-1's three
obligations — were unchecked on nine of ten BP shapes and five of six eGFR
shapes. The output was not merely incomplete: it reported the other passes'
variables as dead and their statics as unused, so a correct map looked broken
and a broken one could look fine.

`fhir_sulo.engine.maplint.lint_map` now lints **once per declared pass**, with
that pass's `staticVars` in scope, exactly as the runner will execute it.

| | walked | errors | warnings |
| --- | --- | --- | --- |
| bp | 10 of 10 root shapes | 0 | 0 |
| egfr | 6 of 6 | 0 | 0 |
| encounter | 9 of 9 | 0 | 0 |

Proved to be real analysis rather than green output by injecting faults into
shapes `start` does not name: an unknown Map function in `sh:BPUnitNode` (pass
`unit`) and an unbound variable in `sh:BPTimeNode` (pass `time`) are both
caught and reported against the pass. `tests/engine/test_engine_live.py` keeps
both.

Two findings changed scope, because per-pass is the wrong grain for them:

* **SP101** (source variable read by nothing) is computed once, over the union
  of every pass's variables — no single pass reads them all — and now consults
  node-key templates and `MapContract.pivot_variables[].target_role`. In this
  architecture a source variable is legitimately consumed by the *host*: as a
  node-key input, an identity or terminology input, or an eligibility guard.
  Calling `panel`, `versionId`, `subjectRef` and `status` dead was the analysis
  being wrong. It now fires only where nothing accounts for a variable at all,
  which is the half-applied rename it was for.
* **SP302** is new: a target shape no pass names and no pass reaches. An
  unreachable shape is an *unlinted* shape, so CD-1's faults live there
  undetected until someone wires it up.

The same derivation (`manifest.host_consumed_variables`) feeds the runner's
binding-coverage check. They have to agree: a variable the linter accepts and
the runner calls dropped data would fail every run of a map that passed its own
gate.

## B1 — the pipeline was three islands

`grep -rln fhir_sulo.engine src benchmarks` returned only the package's own
`__init__`. The maps ran under `tests/contracts/maps/_engine/run-map.js`, whose
own header said to delete it when the driver landed. The store's loader was fed
only by the synthetic benchmark generator. Ingest produced a `SourceContext`
nothing consumed. Each stage was tested and the pipeline did not exist.

`src/fhir_sulo/pipeline/` is the middle:

```
FHIR JSON --[ingest]--> SourceContext
          --[identity + terminology]--> run bindings
          --[ShExMap driver over maps/r4/]--> TransformResult
          --[store]--> a named graph with provenance
```

| Module | Does |
| --- | --- |
| `manifest` | read a run-binding manifest; discovery; host-consumed variables |
| `runner` | manifest + resolved values → passes → `MapRun` → `TransformResult` |
| `services` | policy, ingest, identity, terminology adapters (moved out of `tests/`) |
| `families` | the per-family host work: which service calls a map needs |
| `compose` | the whole path, with eligibility and identity refusal handled first |
| `cli` | `map` and `batch` operator commands |

`fhir_sulo.engine.maprun` is the driver's multi-pass entry point: **bind once,
materialize N times**. Validating ten times to answer one question would be ten
times the work, and it would make "were all bindings consumed?" meaningless per
pass — a binding the diastolic pass reads is legitimately unconsumed by the
systolic one. Coverage is therefore checked once, over the union.

Two rules `compose` exists to keep:

* **Ineligibility stops the run before it starts.** `TransformResult` refuses
  target quads on `source-only` and `rejected`, so an ineligible resource never
  reaches the engine rather than being mapped and then stripped.
* **An unresolved or ambiguous reference is not a person.** The identity
  service declining is a designed outcome and yields `source-only`, not a graph
  with a guessed subject.

### `run-map.js` is gone

Deleted. `tests/contracts/maps/_engine/engine.py` is now a thin adapter: it
builds a `MapJob` and runs it through the production bridge with the driver's
`Guards` and the driver's per-quad provenance. The legacy result-document shape
is preserved deliberately — `require_clean`, `quads`, `triples` and
`objects_of` are used across six of Agent 3's test modules, and repointing the
engine is not a reason to rewrite their assertions. `_engine/mapjob.py` is now
re-exports of `fhir_sulo.pipeline`, so there is one implementation of the
conditional-pass rules rather than two.

**All 98 of Agent 3's map tests pass unchanged**, including the fault-injection
test that feeds the materializer a mutated binding tree — that hook is now
`maprun.materialize_from_bindings`, named and documented as replay-or-injection
rather than an anonymous field on the normal path.

### The no-host-triple guard now runs on the real maps

DR-302 requires the driver to emit no triple of its own, mechanically.
`tests/integration/test_composed_pipeline.py::TestTheHostEmitsNoTripleOfItsOwn`
runs it over the production maps and fixtures — bp with and without a diastolic
component, egfr, encounter — asserting every quad names a TripleConstraint the
family's own target schema declares, that lineage covers every quad, and that
the guard can fail when handed a forged quad. Passing it on a toy pair proved
nothing about the maps that ship.

### Operator surface

```
python -m fhir_sulo.pipeline.cli map   --family bp --quality-mode per-observation <files...>
python -m fhir_sulo.pipeline.cli batch --family bp --quality-mode per-observation \
    --out batch.jsonl --load store/ <files...>
```

`batch` writes the JSON Lines manifest Agent 6's store already reads, and
`--load` applies it, writing `state.json`, `provenance.nq` and `graph.nt`.
Verified end to end: two BP resources → 68 triples in 2 named graphs with
provenance. A non-mapped resource is written too, with its reason and no quads
— loading that line retracts whatever graph the store holds, which is how
`entered-in-error` takes effect. Skipping it would leave the old clinical
assertions standing.

## The engine image tag was shared mutable state

Found while doing the above, and worth its own note because it is a trap for
every agent. `EngineImage.ensure_built()` is a no-op when the tag exists, and
several agent worktrees share one Docker daemon. A bare version tag therefore
means whoever built last wins, and everyone else silently runs an image that
does not match their source tree. It reverted the bridge under a passing test
run in the middle of this work, twice, before the cause was clear.

The tag now carries a hash of the build context (`package.json`,
`package-lock.json`, `Dockerfile`, and every file in `bridge/`):
`fhir-sulo/shexmap:1.0.0-alpha.33-c5fc8dc8b610`. Different bridges get
different tags and cannot clobber each other. `FHIR_SULO_ENGINE_IMAGE` still
overrides, which is how CI can pin a prebuilt image.

## Consequences

- Agent 3: the maps lint clean, so `static_analysis_passed` can go true. That
  flip and the inversion of `test_static_analysis_is_not_claimed` are theirs to
  make; the linter output backing it is `make lint-schemas`.
- Agent 6: the operator guide can drive real FHIR input. Command surface above;
  the guide is theirs to edit.
- A new map family needs a `Family` resolver in `pipeline/families.py`. The
  manifest declares *that* a value comes from a service, not *which call*
  makes it, and that last step is family knowledge.
- `make gate1` already requires Docker; `make lint-schemas` now genuinely runs.
