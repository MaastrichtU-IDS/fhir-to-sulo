# Gate 4 benchmark: measurement protocol and results

**Owner:** Agent 6. **Gate:** 4. **Last measured:** 2026-09-29.

> **Scope warning, stated first because it is the most important thing here.** This benchmark
> does **not** include the transformation. `generator.py` emits SULO target triples directly;
> there is no rendering, no map and no engine in the measured path. The number is a **lower
> bound on end-to-end time**, not the Gate 4 figure. Closing that gap is blocked on Agent 4's
> composed pipeline; the plan is in [DR-605 §5](../docs/fhir-sulo/decisions/DR-605-r5-unset-rejects-and-validation-on-map-output.md).
> Treat the target as **at risk** until it is re-measured with the real maps.

> The benchmark processes 10,000 synthetic resources on a documented
> 4-vCPU/8-GB runner within 15 minutes, with peak memory below 6 GB and no
> unexpected mapping failures. These are pilot engineering targets, to be
> revised only by an explicit performance decision backed by measured
> profiles. — plan §4, Gate 4

## Verdict

| Gate 4 target | Measured | |
| --- | --- | --- |
| 10,000 resources ≤ 15 min | **78.1 min** (4685 s) | **MISSED** |
| peak memory < 6 GB | **5.68 GB** | met, with **5% headroom** |
| no unexpected mapping failures | 9,510 mapped, 490 not, **all 490 explained** | met |

**The time target is missed by 5.2x.** The corpus was not shrunk and the target is
not revised. The diagnosis — two `docker run` invocations per resource, ~65% of the cost being
container start-up rather than mapping work — is in
[DR-606](../docs/fhir-sulo/decisions/DR-606-gate4-scale-measured-on-the-real-pipeline.md),
together with what would fix it.

This is the **first** measurement of the real path. Every earlier Gate 4 number in this
repository measured a pipeline with no mapping in it (DR-604, amended).

## Results, 2026-09-29

Mode: **real pipeline (render + materialize)**. Runner: `--cpus=4 --memory=8g`,
`python:3.11-slim-bookworm` + ROBOT 1.9.7, CPython 3.11.16,
seed 20260929, `--strictness concept-note-literal`,
`--quality-mode per-observation` (R2 and R5 are both open; both named explicitly).

| Stage | Time | Throughput | Peak (cgroup) |
| --- | ---: | ---: | ---: |
| `generate` | 0.04 s | 258518.4/s | 0.04 GB |
| `render` | 2.32 s | 4302.9/s | 0.16 GB |
| `materialize` | 4491.47 s | 2.2/s | 3.27 GB |
| `keying+lineage+store` | 1.00 s | 9968.5/s | 3.30 GB |
| `provenance` | 0.65 s | 15283.9/s | 3.37 GB |
| `shacl validation` | 85.43 s | 3057.8/s | 4.05 GB |
| `owl reasoning (HermiT)` | 104.19 s | 19.1/s | 5.68 GB |
| **TOTAL** | **4685.11 s** | 2.1 res/s | **5.68 GB** |

The peak column is the cgroup's high-water mark, which is monotonic, so each row is the peak
*so far* rather than that stage's own usage. Read down the column: the pipeline sits at 3.3 GB
until SHACL, and **OWL reasoning adds the last 1.6 GB**, ending 0.32 GB under the limit.

**`materialize` is 95.9% of the run** — 4,491 s of 4,685 s, at 0.472 s per mapped resource.
Everything else together is 194 s. Time spent on the transformation is therefore the only thing
worth optimising, and DR-606 shows most of that is not transformation work either.

**Memory is a near miss, not a comfortable pass.** 5.68 GB against a 6 GB limit is 5% of
headroom, and the consumer is the reasoning stage, whose cost scales with the *number of
encounters*. This corpus is 19.9% encounters (1,987 of 10,000). A corpus with more of them, or
a larger `--reason-batch`, would exceed 6 GB. `--reason-batch` is the control: it trades peak
memory against JVM start-ups, and 100 was chosen for time, not for memory.

### Failure categories

Plan Gate 4 requires "no unexpected mapping failures". 490 of 10,000 resources produced no
graph, and **every one is an expected, policy-declared outcome** with a reason from the pinned
status policy — not an engine error, a crash or a timeout. `render failures: 0`, and no
`materialize: <Exception>` category appears. That clause could not be shown at all until this
run, because there was no mapping in the measured path.

| category | count |
| --- | ---: |
| Observation.dataAbsentReason present: Concept note section 4: dataAbsentReason produces no numeric hasValue. | 262 |
| Observation.status 'entered-in-error' is source-only under the pinned status policy | 228 |

### The ShExMap engine

`engine_bench/run.sh`, same constraints, `node:20-bookworm-slim`,
`shex@1.0.0-alpha.33`, `maxAccepts`/`maxRepeat`/`maxSteps`/`exploreSteps`
raised per DR-301 decision 1.

**Part A — N separate materializations of a 2-component panel.** The shape the
pilot actually runs:

| N | total | per resource | resources/s |
| ---: | ---: | ---: | ---: |
| 100 | 0.009 s | 0.090 ms | 11,111 |
| 1,000 | 0.051 s | 0.051 ms | 19,608 |
| 5,000 | 0.160 s | 0.032 ms | 31,250 |
| **10,000** | **0.301 s** | **0.030 ms** | **33,223** |

Per-resource cost *falls* by 3× as N grows — JIT warm-up, not superlinearity.
Linear. 0.3 s out of a 15-minute budget.

**Part B — one materialization with N components.** Agent 4's curve,
reproduced:

| N | time | µs / N² | quads |
| ---: | ---: | ---: | ---: |
| 100 | 21 ms | 2.100 | 301 |
| 250 | 126 ms | 2.016 | 751 |
| 500 | 476 ms | 1.904 | 1,501 |
| 1,000 | 2,043 ms | 2.043 | 3,001 |
| 2,000 | — | — | **OOM** |

Time is quadratic: µs/N² is flat at ≈2.0 across a 10× range. Output is linear
(3N+1), so the cost is in the search, not the result. At N = 2,000 Node's
default heap is exhausted — *"FATAL ERROR: Ineffective mark-compacts near heap
limit"* — after the cgroup peaked at **4.66 GB**.

**The diagnosis.** The quadratic term is in the number of repetitions *inside
one materialization*, not in the number of resources. DR-302 constrains every
map to one repetition level rooted at one FHIR resource, so N is 2 for a BP
panel and 2 for an encounter's participants. 10,000 resources is 10,000 tiny
materializations, and the total is linear. **The engine is not the Gate 4
risk.** It becomes one immediately if DR-302 is ever relaxed — a Bundle-rooted
map over 2,000 entries is Part B, and Part B does not finish.

### An independent argument for CD-2

**Part A2** measures binding extraction through the shipped `shex-validate`
CLI: **101.7 ms per resource**, which extrapolates to **1,017 s (17 min)** for
10,000 — over the Gate 4 budget on that stage alone. Almost all of it is Node
process spawn; an in-process validation of the same graph measures 0.07 ms.

CD-2 bans the shipped CLI because it silently truncates and exits 0 on
failure. This adds a second, independent reason: **it cannot meet the
performance target either.** The number to hold Agent 4's driver to is the
in-process one.

## 4. Honest caveats

1. **The end-to-end pipeline does not exist yet.** 194 s is the host layers plus reasoning.
   Ingestion, the real maps and the driver are not in it. This is the single largest caveat and
   it is why the Gate 4 scale row should not be read as passed. See DR-605 §5 for the plan.
2. **The maps are stand-ins.** Real schemas are larger and materialization
   cost depends on schema size. Re-measure against `maps/r4/`.
3. **Reasoning is batched at 100 encounters.** Sound, because the PRO chain is
   local to one encounter and never crosses resources — but it is a choice,
   and `--reason-batch` exposes it. Un-batched reasoning over 10,000 resources
   does not finish in a useful time.
4. **`-t structural` is load-bearing.** Without it the property-assertion
   generator emits O(n²) tautologies per batch (95,949 inferred lines for 40
   encounters, versus 2,924 with it). The PRO entailment is not a tautology
   and survives; `test_reasoning_pro.py` checks that with the setting active.
5. **CPython 3.11 in the image, 3.9 on the host.** The code targets 3.9; the
   image uses 3.11. Python version affects the host-stage numbers somewhat and
   nothing else.
6. **One run, not a distribution.** These are single measurements on one
   machine's Docker. They are reproducible via the image, but no variance is
   reported. If a future number is close to a limit, run it several times.

## 5. Files

| File | Purpose |
| --- | --- |
| `Dockerfile` | the documented runner: Python + the pinned ROBOT jar |
| `run.sh` | builds it, applies the constraints, ships the tree in, runs |
| `generator.py` | deterministic synthetic corpus |
| `harness.py` | stage timing and cgroup peak memory |
| `run_benchmark.py` | the stages, and `--emit-batch` for the operator guide |
| `engine_bench/` | the ShExMap engine measurement |
| `last-report.json` | the most recent machine-readable report |
