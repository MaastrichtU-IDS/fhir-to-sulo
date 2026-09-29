# DR-606 — Gate 4 scale, measured on the real pipeline: MISSED, with a diagnosis

**Status:** Measured (Agent 6). **The Gate 4 scale row does not pass.**
**Date:** 2026-09-29
**Gate:** 4
**Supersedes:** [DR-604](DR-604-benchmark-protocol-and-gate4-result.md) as the Gate 4 scale
result, and [DR-605 §5](DR-605-r5-unset-rejects-and-validation-on-map-output.md) as the plan
**Depends on:** DR-304 (the composed pipeline), DR-301 B2, DR-302, DR-602

## Result

> The benchmark processes 10,000 synthetic resources on a documented 4-vCPU/8-GB runner within
> 15 minutes, with peak memory below 6 GB and no unexpected mapping failures. — plan §4, Gate 4

| Target | Measured | |
| --- | --- | --- |
| 10,000 resources ≤ **15 min** | **78.1 min** (4,685.11 s) | **MISSED, by 5.2x** |
| peak memory < **6 GB** | **5.68 GB** | met, with **5% headroom** |
| no unexpected mapping failures | 9,510 mapped, 490 not, **all 490 explained** | met |

**The time target is missed by 5.2x.** The corpus was not shrunk and the target is not being
revised. The diagnosis points at a specific, fixable cause that is not in the mapping itself.

| Stage | Time | Share |
| --- | ---: | ---: |
| generate | 0.04 s | |
| render | 2.32 s | 0.05% |
| **materialize** | **4,491.47 s** | **95.9%** |
| keying+lineage+store | 1.00 s | 0.02% |
| provenance | 0.65 s | 0.01% |
| shacl validation | 85.43 s | 1.8% |
| owl reasoning (HermiT) | 104.19 s | 2.2% |

261,236 target triples emitted; SHACL conforms on all of them under
`concept-note-literal`; 1,987 encounters reasoned, 163,233 triples inferred.

**Two results worth separating from the miss.**

*"No unexpected mapping failures" is satisfied, and could not even be asked before.* 490 of
10,000 produced no graph and every one is a policy-declared outcome - 262 `dataAbsentReason`,
228 `entered-in-error` - with a reason from the pinned status policy. Zero render failures,
zero engine exceptions.

*Memory is a near miss, not a comfortable pass.* The cgroup peak is monotonic, so the stage
column reads as a running high-water mark: the pipeline sits at 3.3 GB through materialize,
store and provenance, SHACL takes it to 4.05 GB, and **OWL reasoning adds the last 1.6 GB**,
finishing 0.32 GB under the limit. That consumer scales with the number of *encounters*, which
is 19.9% of this corpus. A corpus with more encounters, or a larger `--reason-batch`, would
exceed 6 GB. `--reason-batch 100` was chosen for time, not for memory, and it is the control.

Every previous Gate 4 number in this repository measured a path with **no mapping in it**
(DR-604, amended). This is the first measurement of the real thing.

## What changed to make this measurable

Agent 4's composed pipeline (DR-304) joined ingest, the maps and the store. The benchmark now
runs:

| stage | what it is |
| --- | --- |
| `generate` | synthetic **FHIR R4 JSON** |
| `render` | Agent 2's ingest: JSON → `SourceContext` + FHIR RDF |
| `materialize` | Agent 3's maps through Agent 4's pinned engine |
| `keying+lineage+store` | graph key, per-quad lineage, named graph load |
| `provenance` | PROV-O for every run |
| `shacl validation` | the target shape contract over the accumulated graph |
| `owl reasoning (HermiT)` | the PRO entailments, batched |

`--synthetic-targets` keeps the old behaviour — the generator emitting SULO triples directly,
no `render`, no `materialize` — for timing the host layers in isolation and bisecting a
regression to one stage. It is not a Gate 4 result and the report labels the mode.

## The diagnosis

**Two `docker run --rm -i` invocations per resource, and container start-up dominates.**

Measured on the pilot host, before the full run:

| | |
| --- | --- |
| bare `docker run --rm -i <engine> node -e 0` | **0.169 s** |
| engine invocations per resource | **2** (one binding pass, one materialization pass) |
| therefore container start-up per resource | **0.339 s** |
| total pipeline cost per resource | **0.472 s** measured over 9,510 mapped resources |
| **share that is container start-up** | **~72%** |

And the cost is flat across families — eGFR 0.503 s (21 quads), BP 0.552 s (34 quads),
Encounter 0.519 s (29 quads). If schema complexity or triple count drove the cost, BP's ten-pass
map would stand out. It does not. **This is per-invocation overhead, not mapping work.**

For comparison, the engine's *actual* materialization work was measured at **0.030 ms** per
resource (`engine_bench` Part A, 10,000 two-component panels in 0.301 s) — four orders of
magnitude below the per-resource cost being paid.

So the Gate 4 time is not being spent on the transformation. It is being spent starting and
tearing down 20,000 containers.

## What would fix it

Not a tuning flag. `EngineImage.call` hardcodes `docker run --rm -i` per call
(`src/fhir_sulo/engine/docker.py`), which is Agent 4's file and a deliberate design: DR-301's
operational note records that bind mounts silently present an *empty* directory under colima, so
the image carries everything and each call is self-contained. That choice removed a real trap and
should not be reverted casually.

Three ways out, in order of how much they change:

1. **A long-lived engine container.** `docker run -d` once, then `docker exec` per call — or,
   better, one persistent Node process reading requests from stdin. Removes the 0.339 s and lets
   the parsed schemas stay in memory between resources. This is the same change that took the
   ROBOT reasoner from a container per call to a container per run. **Removing container
   start-up alone leaves ~0.13 s per resource, so ~22 min for 10,000 — still over budget, but
   within reach of fix 2.** That estimate is conservative: it assumes only the container cost
   goes, while a persistent Node process would also stop re-parsing the schemas on every
   resource.
2. **Batch resources per invocation.** The maps are rooted at one resource (DR-302) and the
   engine's per-materialization cost is negligible, so N resources can share one invocation with
   no change to the schemas and no cross-resource binding. Combined with fix 1 this should put
   10,000 resources in the low minutes.
3. **Parallelism.** Resources are independent — nothing in the pipeline crosses them (this is
   also why the reasoner can batch, DR-602 §5). Four workers on a 4-vCPU runner is a legitimate
   4x, and needs no semantic change. Worth doing *after* 1 and 2, because parallelising a
   container-start-up bottleneck mostly multiplies container start-ups.

**Recommended owner: Agent 4**, since it is their engine interface. Fixes 1 and 2 are the ones
that matter; 3 is a multiplier on whatever they leave.

## What is *not* the problem

- **Not the maps.** Flat cost across three families of very different sizes.
- **Not the host layers.** Keying, lineage, the store and provenance together are **1.65 s**
  for 10,000 resources. SHACL (85 s) and reasoning (104 s) are linear and together are 4% of
  the run.
- **Not ingest.** Rendering 10,000 FHIR resources to RDF takes **2.32 s**.
- **Not the engine's algorithmic behaviour.** DR-604 established that DR-302's one-repetition
  constraint keeps the engine's quadratic term out of reach; that still holds, and
  `engine_bench` Part B still reproduces the quadratic curve for the configuration the pilot
  never runs.
- **Not memory.** See the table; the peak is well inside 6 GB.

## Honest caveats about the measurement

1. **The runner constraint does not reach the engine containers.** The benchmark container has
   `--cpus=4 --memory=8g` and the Docker socket mounted, so the pipeline can spawn the engine.
   Those engine containers are **siblings**, not children: they are outside the benchmark's
   cgroup and get the whole host. Constraining them needs an option on `EngineImage`, which
   hardcodes its `docker run` arguments — requested from Agent 4, not worked around.
   **This makes the measured time a lower bound**, so the MISS is conservative: a runner that
   really confined everything to 4 vCPUs would be slower, not faster.
2. **Peak memory is the benchmark cgroup's**, for the same reason. The engine containers'
   memory is not in it. Each is short-lived and small and they run sequentially, so the true
   peak is close — but it is not measured, and 5.68 GB should be read as the host stages' peak.
   Given only 5% headroom, that unmeasured margin matters: **do not read the memory row as
   comfortably met.**
3. **The corpus is synthetic FHIR JSON**, shaped after Agent 2's committed fixtures so it
   exercises the elements the maps were reviewed against. It is not clinical data, which the
   pilot's scope forbids anyway.
4. **One run, not a distribution.**

## Consequence for the gate

`tools/gate-check.py` should report Gate 4's scale row as **FAIL** on this report, and that is
the correct state of the pilot. A missed row that is honestly measured is worth more than a met
row that measured a path with no mapping in it — which is what the repository had until today.

Nothing here revises the target. Plan §4: *"These are pilot engineering targets, to be revised
only by an explicit performance decision backed by measured profiles."* This is the measured
profile; the decision it supports is to fix the engine invocation, not to move the target.
