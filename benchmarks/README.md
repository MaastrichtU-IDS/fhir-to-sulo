# Gate 4 benchmark: measurement protocol and results

**Owner:** Agent 6. **Gate:** 4. **Last measured:** 2026-09-29.

> The benchmark processes 10,000 synthetic resources on a documented
> 4-vCPU/8-GB runner within 15 minutes, with peak memory below 6 GB and no
> unexpected mapping failures. These are pilot engineering targets, to be
> revised only by an explicit performance decision backed by measured
> profiles. — plan §4, Gate 4

## Verdict

**Both targets met, with one scope caveat stated below.**

| Target | Result |
| --- | --- |
| 10,000 resources ≤ 15 min | **3.0 min** (179.25 s) |
| peak memory < 6 GB | **2.01 GB** |
| failure categories reported | yes, 487 of 10,000 by design |
| engine contribution | **0.30 s** for 10,000 materializations |

Agent 4 measured the engine scaling quadratically and the brief called the
target at risk on that basis. It is not at risk, and §3 explains exactly why
the quadratic term does not reach us — it is an architectural consequence of
DR-302, not luck, so it will stay true only as long as DR-302 does.

## 1. What is and is not measured

Measured, over 10,000 synthetic resources:

| Stage | What it exercises |
| --- | --- |
| generate | the synthetic corpus itself |
| keying+lineage+store | graph keys, per-quad lineage construction, named graph load, correction bookkeeping |
| provenance | PROV-O emission for every run |
| shacl validation | the full target shape contract over the accumulated graph |
| owl reasoning | HermiT over every encounter, batched |

Measured separately, in `engine_bench/`: the pinned ShExMap engine.

**Not measured, and therefore not in the total:** FHIR JSON validation and RDF
rendering (Agent 2), the real reviewed maps (Agent 3), and the materialization
driver (Agent 4). The number is a **lower bound on end-to-end time**. When
those land, re-run; the stage table is built so the new stages slot in and the
old ones stay comparable.

The target graphs the benchmark loads are produced by `generator.py`
directly. That is a **performance stand-in, not a map.** It exists so the host
layers can be measured at scale before the maps exist, and the shapes it emits
are the concept note's patterns so that the SHACL and reasoning stages do real
work. It must not be mistaken for a FHIR-to-SULO mapping.

## 2. The runner

`benchmarks/run.sh` builds `Dockerfile` and runs it with `--cpus=4
--memory=8g --memory-swap=8g`. The constraints are not optional and are not a
flag: a "4-vCPU/8-GB runner" that is actually a 14-core laptop measures the
laptop. The report reads the limits back out of `/sys/fs/cgroup` and prints
them, so a number can always be checked against the envelope that produced it.

Peak memory is the **cgroup** peak, not `ru_maxrss`. The reasoner forks a JVM;
a per-process figure would miss the single largest consumer. Where no cgroup
is readable the report says `unknown`, never a smaller number.

One image holds both Python and ROBOT, so the host stages and the reasoning
stage share a cgroup. Two separately-constrained containers would under-report
the peak, because the peak of a sum is not the sum of peaks.

ROBOT is **copied** into the image from the digest
`obolibrary/robot@sha256:58da5acb…`, the same one `validation/reasoning.py`
pins and the same one the PRO entailment was verified against. It is not
re-downloaded, so the benchmark cannot drift onto a different reasoner build.

```
benchmarks/run.sh                      # 10,000 resources
benchmarks/run.sh -n 1000              # smaller trial
benchmarks/run.sh --strictness R5_OPTION_A     # cost of the strict shapes
BENCH_CPUS=2 BENCH_MEMORY=4g benchmarks/run.sh # a different envelope
benchmarks/engine_bench/run.sh         # the ShExMap engine
```

## 3. Results, 2026-09-29

Runner: `--cpus=4 --memory=8g`, `python:3.11-slim-bookworm` + ROBOT 1.9.7,
CPython 3.11.14, seed 20260929, strictness `concept-note-literal` (R5 open).
Corpus: 4,019 eGFR, 3,535 BP panels, 1,959 encounters, 487 ineligible;
220,015 target triples.

| Stage | Time | Throughput | Peak (cgroup) |
| --- | ---: | ---: | ---: |
| generate | 0.10 s | 103,590 res/s | 0.06 GB |
| keying + lineage + store | 1.53 s | 6,542 res/s | 0.20 GB |
| provenance | 0.61 s | 16,287 res/s | 0.30 GB |
| SHACL validation | 84.94 s | 2,590 triples/s | 0.71 GB |
| OWL reasoning (HermiT) | 92.07 s | 21.3 enc/s | **2.01 GB** |
| **TOTAL** | **179.25 s** | 55.8 res/s | **2.01 GB** |

Failure categories, all by construction: 246 `dataAbsentReason`, 241
`entered-in-error`. Both take the `source-only` path and contribute no
clinical assertions, which is what concept note §2 requires.

SHACL scales linearly — 2.42 s / 4.95 s / 9.10 s / 18.16 s at n = 250 / 500 /
1000 / 2000 — which was worth checking, because the orphan-node constraint is
a `FILTER NOT EXISTS` evaluated per focus node and would have been quadratic
without an object index.

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

1. **The end-to-end pipeline does not exist yet.** 179 s is the host layers
   plus reasoning. Ingestion, the real maps and the driver are not in it.
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
