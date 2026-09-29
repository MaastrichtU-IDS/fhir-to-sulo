# DR-301 — ShEx.js engine pin and Gate 1 capability verdict

**Status:** Decided (Agent 4, verified independently by Agent 1)
**Date:** 2026-09-29
**Gate:** 1

## Pin

| Item | Value |
| --- | --- |
| `shex` | `1.0.0-alpha.33` |
| `@shexjs/extension-map` | `1.0.0-alpha.33` |
| Runtime | `node:20-bookworm-slim` (node v20.20.2) |
| Install | `npm ci` against the committed `tools/engine/package-lock.json` (245 packages, integrity hashes) |
| Entry point | **`ThreadedMaterializer` via the programmatic API.** The shipped CLI is banned — see B2/B3. |

The npm release is sufficient. No git build or upstream patch is required to pin.

## Verdict: CONDITIONAL GO

Reproduced from clean by the integration lead, not accepted on report:

```
$ tools/engine/run.sh
PASS   1  install & surface: shex-validate, shexmap-materialize, shexmap-debug + ThreadedMaterializer API
PASS   2  minimal end-to-end materialization
PASS   3  iteration scopes, ONE level of repetition: pairs stay associated under every triple order
FAIL   3b iteration scopes, TWO levels of repetition -- groups mis-associated AND a panel is lost
FAIL   3c two outer groups with no outer variable collapse into one (expected: 2)
FAIL   3d two levels with only ONE inner element each is still mis-associated
PASS   4a bnode labels + output are byte-identical across runs (deterministic)
FAIL   4b no id() function: '%Map:{ id(v:x) %}' silently prunes the whole shape
FAIL   4c a Map var on a shape-valued constraint emits the IRI as a LEAF and drops the sub-shape
PASS   5  per-quad lineage via API: materializer.provenance[] + frameOrigins[]
PASS   6  inverse/pivot: target graph revalidates and yields identical bindings; full round trip
FAIL   7  no static checker ships; unbound target variables only surface at runtime
PASS   8a validation failures are machine-parseable JSON (shex-validate exits 1)
FAIL   8b shexmap-materialize EXITS 0 on a fatal materialization error and prints an empty graph
FAIL   8c an unbindable target variable silently yields a PARTIAL graph, exit 0, nothing on stderr
PASS   10 WORKAROUND: N one-level maps joined on the group IRI reproduce the two-level map exactly
FAIL   11a the CLI silently emits at most 19 of N repetitions (maxAccepts defaults to 20)
PASS   11b raising maxAccepts through the API removes the cap (200/200, 500/500)
PASS   9  upstream fixtures: 7/8 reproduce (the miss is a staticVar absent from the stored expectation)
```

Full evidence, with reproducers, in [`engine-findings.md`](../engine-findings.md).
Probes are committed under `tools/engine/probes/` and are individually runnable.

## What this buys us

- **The blood-pressure requirement is met at one level.** Two components stay associated under
  five input permutations — reversed within-panel order, fully interleaved triples, blank nodes,
  three panels. No cross-join. `alpha.33`'s `ThreadedMaterializer` (per-thread binding cursor)
  genuinely fixes the classic value-bag problem, which is precisely the failure the ShExMap
  Repository implementation exhibits (DR-004).
- **Determinism**, byte-identical across runs including blank-node labels — the precondition for
  Gate 4 idempotence.
- **Bidirectional pivot recovery**, which is the acceptance row "Pivot reversibility".
- **Per-quad lineage** via `materializer.provenance[]` (parallel to the emitted quads, each
  `{quad, tc, predicate, src}`) and `frameOrigins`. It reaches the *binding*; joining binding to
  source triple is host work. Agent 6 should wire this from day one — it is free now and
  expensive to retrofit.

## Blockers, all of which fail *silently*

**B1 — two levels of repetition are mis-mapped, and this is specified behaviour.**
Patient → 2 reports → 2 panels each yields a mislabelled report, an empty report, and one panel
missing. Exit 0, empty stderr. The cause is structural: `normalizeBindingTree` flattens a correct
nested binding tree into a frame tape with no outer-group boundary and duplicates outer variables
into every inner frame. Upstream's own `BPPatient-2-levels` fixture *expects* the flattened output
and is marked conformant, so this is not a bug we can report — it is the contract.
**Consequence: a whole-Bundle map is ≥2 levels and would produce a wrong graph.** See DR-302.

**B2 — the CLI silently truncates every repetition to 19 items.** 60 panels in, 19 out, exit 0,
nothing on stderr. `maxAccepts` defaults to 20 and `bin/materialize` cannot set it. Raising it
through the API gives 200/200 and 500/500. Scaling is quadratic (1000 in 2.1 s, 2000 in 12.4 s),
which matters for the Gate 4 benchmark.

**B3 — `shexmap-materialize` exits 0 on fatal errors and on partial output**, with nothing on
stderr. Unusable in a pipeline at any scale. (`shex-validate` is well-behaved: exits 1, emits
parseable JSON.)

Further gaps: **no `id()`** (only `hashmap`, `regex`, `test`), and an unknown Map function
*silently deletes the entire shape that used it*. Only the root node's IRI is controllable.
**No static checker ships** — `--diagnose` crashes non-TTY with exit 99. Blank-node counters
restart at `_:tm0` per materialization, so naively concatenating two outputs silently merges
unrelated blank nodes.

## Decisions taken

1. **Ban `shexmap-materialize` and every shipped CLI materialization path.** Drive
   `ThreadedMaterializer` from the API with `maxAccepts`, `maxRepeat`, `maxSteps` and
   `exploreSteps` raised explicitly. Non-negotiable given B2 and B3: both fail silently, and a
   silent partial graph is the single worst failure mode for this pilot.
2. **One repetition per path** becomes an architectural constraint on every schema pair. DR-302.
3. **Two named host-side tools are funded**, owned by Agent 4, and explicitly *not* postprocessors
   (see DR-302 for why this is not rule-hiding):
   - a **schema-pair linter** enforcing the no-nested-repetition rule and unbound-variable
     detection, standing in for the absent static checker (acceptance row "Mapping analysis");
   - a **materialization driver** enforcing fail-fast on `MaterializationError`, non-empty
     `lastReport.unboundVariables`, `explorationTruncated`, and bindings-not-fully-consumed,
     plus blank-node-safe union across passes.
3. **Node identity** comes from the per-group source IRIs the decomposition yields, with blank
   nodes accepted below them. See the contract deviation note on `id()`.

## Operational note

Colima shares only the VM owner's home directory, so **bind mounts into the scratchpad do not
work on this machine**. `tools/engine/run.sh` ships the tree into the container with `docker cp`
instead. Any agent mounting host paths into Docker must do the same.
