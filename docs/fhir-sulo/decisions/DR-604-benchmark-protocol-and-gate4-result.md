# DR-604 — Benchmark protocol, and the Gate 4 scale result

**Status:** Decided (protocol) and **measured** (result)
**Date:** 2026-09-29
**Gate:** 4
**Depends on:** DR-301 B2 (the engine's quadratic scaling), DR-302, DR-602

## Result

| Gate 4 target | Measured |
| --- | --- |
| 10,000 synthetic resources ≤ 15 min | **179.25 s (3.0 min)** |
| peak memory < 6 GB | **2.01 GB** |
| failure categories and throughput reported | yes — 55.8 resources/s, 487 ineligible by design |
| ShExMap engine over 10,000 resources | **0.30 s** |

**The target is met.** The brief flagged it as at risk on the strength of Agent 4's quadratic
measurement. §3 explains why the quadratic term does not reach us, and under what change it
would.

Full stage table, protocol and caveats: [`benchmarks/README.md`](../../benchmarks/README.md).

## 1. The protocol, and why it is shaped this way

**The runner is a file, not a machine.** `benchmarks/Dockerfile` plus `run.sh`, which applies
`--cpus=4 --memory=8g --memory-swap=8g`. The constraints are not a flag an operator can forget:
a "4-vCPU/8-GB runner" that is actually a 14-core laptop measures the laptop. The report reads
the limits back out of `/sys/fs/cgroup` and prints them, so a number can always be checked
against the envelope that produced it.

**Peak memory is the cgroup peak**, not `resource.getrusage`. The reasoner forks a JVM; a
per-process figure would miss the largest consumer in the pipeline. Where no cgroup is readable
the report prints `unknown`, never a smaller number.

**One image, not two.** Python and ROBOT share a container so the host stages and the reasoning
stage are measured in the same cgroup. Two separately-constrained containers would under-report
the peak: the peak of a sum is not the sum of peaks. ROBOT is **copied** from the digest
DR-602 pins rather than re-downloaded, so the benchmark cannot drift onto a different reasoner.

**The engine is measured separately** (`engine_bench/`, `node:20-bookworm-slim`, same
constraints) because it needs Node and because the maps it would run are Agent 3's.

## 2. What the number does and does not cover

In it: synthetic generation, graph keying, per-quad lineage construction, named graph loading
and correction bookkeeping, PROV-O emission, SHACL validation, OWL reasoning.

**Not in it:** FHIR JSON validation and RDF rendering (Agent 2), the reviewed maps (Agent 3),
the materialization driver (Agent 4). **179 s is a lower bound on end-to-end time.** The stage
table is built so those slot in and the existing stages stay comparable.

The target graphs are produced by `generator.py` directly. That is a **performance stand-in, not
a map** — it exists so the host layers can be measured at scale before the maps exist. The
shapes it emits are the concept note's patterns, so the SHACL and reasoning stages do real work.

## 3. The engine: the risk, measured

Agent 4 measured 1000 panels in 2.1 s and 2000 in 12.4 s. Both curves were re-measured.

**Part A — the shape the pilot runs** (N separate materializations, 2 components each):

| N | total | per resource |
| ---: | ---: | ---: |
| 100 | 0.009 s | 0.090 ms |
| 1,000 | 0.051 s | 0.051 ms |
| 10,000 | **0.301 s** | 0.030 ms |

Per-resource cost *falls* 3× as N grows — JIT warm-up, not superlinearity. Linear.

**Part B — Agent 4's curve, reproduced** (one materialization, N components):

| N | time | µs / N² |
| ---: | ---: | ---: |
| 100 | 21 ms | 2.100 |
| 500 | 476 ms | 1.904 |
| 1,000 | 2,043 ms | 2.043 |
| 2,000 | **OOM** | — |

µs/N² is flat at ≈2.0 across a 10× range: quadratic, confirmed. Output is linear (3N+1 quads),
so the cost is in the search, not the result. At N = 2,000 Node's default heap is exhausted
(*"Ineffective mark-compacts near heap limit"*) after the cgroup peaked at **4.66 GB** — worse
than Agent 4's 12.4 s, which is worth knowing.

**The diagnosis.** The quadratic term is in the number of repetitions **inside one
materialization**, not in the number of resources. DR-302 constrains every map to one repetition
level rooted at one FHIR resource, so N is 2 for a BP panel and 2 for an encounter's
participants. 10,000 resources is 10,000 tiny materializations, and the total is linear.

**This is a consequence of DR-302, not luck.** If DR-302 were relaxed — a Bundle-rooted or
Patient-rooted map — the pilot would be running Part B, and Part B does not finish. DR-302 was
adopted for correctness (DR-301 B1 mis-associates groups at two levels); it turns out to be load-
bearing for performance too. Gate 5's `MedicationAdministration` and any Bundle-level ambition
must be checked against both (CD-3).

## 4. A second, independent argument for CD-2

Binding extraction through the shipped `shex-validate` CLI measures **101.7 ms per resource** —
**1,017 s (17 min)** extrapolated to 10,000, over the whole Gate 4 budget on that stage alone.
Almost all of it is Node process spawn; an in-process validation of the same graph measures
0.07 ms.

CD-2 bans the shipped CLI because it silently truncates at 19 repetitions and exits 0 on fatal
errors. This adds a second reason: **it cannot meet the performance target either.** The number
to hold Agent 4's driver to is the in-process one.

## 5. Two findings from the other stages

**SHACL is linear**, which was worth checking rather than assuming: the orphan-node constraint
is a `FILTER NOT EXISTS { ?s ?p $this }` evaluated per focus node, which is quadratic without an
object index. Measured 2.42 / 4.95 / 9.10 / 18.16 s at n = 250 / 500 / 1000 / 2000. 85 s at
10,000.

**Reasoning needed two changes to be viable**, both recorded in DR-602:

1. `-t structural`, which removes O(n²) tautological inferences per batch — 95,949 inferred
   lines down to 2,924 for 40 encounters. Not tuning: without it the stage's output grows
   quadratically in batch size.
2. Batching at 100 encounters. Sound because the PRO chain is local to one encounter and never
   crosses resources. Reasoning 10,000 resources as one ontology does not finish in useful time.

Result: 92 s for 1,959 encounters, ~21 encounters/s, peak 2.01 GB — the largest single consumer
in the run, and the reason the memory figure is what it is.

## 6. Honest caveats

1. **The end-to-end pipeline does not exist yet.** Re-measure when Agents 2–4 land.
2. **The maps are stand-ins.** Real schemas are larger and materialization cost depends on
   schema size.
3. **Reasoning batch size is a choice**, exposed as `--reason-batch`, and it is sound only while
   no entailment crosses resources. If a later map introduces one, this must be revisited.
4. **CPython 3.11 in the image, 3.9 on the host.** The code targets 3.9.
5. **One run, not a distribution.** Reproducible via the image, but no variance is reported. A
   future number close to a limit should be run several times.
6. **The headroom is real but not unlimited.** 179 s against 900 s is 5×. The two dominant
   stages are both linear, so 10,000 → 50,000 resources would land near the limit; that is the
   point at which a performance decision, not a softened target, is needed.
