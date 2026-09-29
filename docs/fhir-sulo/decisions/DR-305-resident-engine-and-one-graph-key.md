# DR-305 — A resident engine, and one graph key instead of two

**Status:** Decided and implemented
**Date:** 2026-09-29
**Gate:** 4 (scale row), plus a correctness fix that binds Gates 2–5
**Fixes:** the Gate 4 scale miss; the two coexisting `graph_key` functions
**Owner:** Agent 4

## 1. The scale miss was container start-up, not mapping

Agent 6's profile: `materialize` was 95.9% of a 78.1-minute run, at 0.472 s per
mapped resource, of which `docker run` start-up was 0.339 s — paid **twice**
per resource, once to bind and once to materialize. Actual materialization is
0.030 ms. We were spending four orders of magnitude more starting a container
than doing the work, and the flat cost across families (eGFR 21 quads, BP 34,
Encounter 29, all ≈0.5 s) said so plainly.

So the engine now stays resident. `tools/engine/bridge/server.js` reads
newline-delimited JSON requests on stdin and writes responses on stdout;
`fhir_sulo.engine.session.EngineSession` owns the process.

**What did not change is the point.** It is the same `docker run --rm -i`, the
same image, the same JSON-on-stdin transport, and still **nothing
bind-mounted** — DR-301's colima trap, where an unshared bind mount silently
yields an empty directory, is untouched. The container is **anonymous**: a
*named* long-lived container is shared mutable state between agent worktrees,
which is exactly where CD-5 and Agent 3's raced job document came from. This
one is owned by one host process, is discoverable by nothing else, and dies
when that process's stdin closes — including on SIGKILL, so cleanup is not
something anyone has to remember.

The other half of the win is the schema cache: the benchmark re-parsed a
153-line ShExC document for each of 10,000 resources. Schemas are now parsed
once per `(text, baseIRI)` and reused, with a bounded cache so a long run
cannot grow.

### Measured, same corpus, same runner (`--cpus=4 --memory=8g`)

| Stage | Before | After | |
| --- | ---: | ---: | ---: |
| render | 2.3 s | 2.0 s | 1.2× |
| **materialize** | **4491.5 s** | **46.0 s** | **97.7×** |
| keying+lineage+store | 1.0 s | 1.0 s | — |
| provenance | 0.7 s | 0.6 s | — |
| shacl validation | 85.4 s | 85.6 s | — |
| owl reasoning (HermiT) | 104.2 s | 93.3 s | 1.1× |
| **TOTAL** | **4685.1 s (78.1 min)** | **228.4 s (3.8 min)** | **20.5×** |
| peak memory | 5.68 GB | **4.97 GB** | |

| Gate 4 row | Target | Result |
| --- | --- | --- |
| time | ≤ 15 min | **PASS — 3.8 min**, 3.9× headroom |
| memory | < 6 GB | **PASS — 4.97 GB**, 17% headroom (was 5%) |
| no unexpected mapping failures | — | **PASS** |

**Output is unchanged**: 9,510 mapped, 490 not, 261,236 target triples — the
same three numbers as the 78-minute run. That is the claim that mattered, and
it is checked directly rather than inferred:
`tests/engine/test_session.py::TestResidentOutputEqualsOneShot` runs each
family through a resident engine and a one-shot engine and requires the quads,
the lineage and the graph key to be identical; it also interleaves families
through one process and repeats a run ten times, because a schema cache and a
reused process are precisely the things that could make a second answer differ
from the first.

### Batching: built, measured, and not needed

Batching was the suggested step 2, and it is safe under DR-302 — every map is
rooted at one FHIR resource and nothing crosses resources, so a batch is N
independent runs sharing a process. `run-map-batch` exists and is tested
(including that one bad item does not abandon the rest, which is the failure
mode worth guarding: 10,000 in, 9,000 out, no error).

**It is not enabled, because the measurement says it would buy about 1%.** A
resident round trip costs 0.28 ms against 42 ms of real work per resource;
batching amortises the round trip, and the round trip is now 1.3% of the cost.
`materialize` is 20% of the run; SHACL (85.6 s) and HermiT (93.3 s) now
dominate. Adding batch plumbing to the pipeline would complicate the path that
carries the no-host-triple guard in exchange for a percent. Recorded as
available if the shape of the work changes.

Parallelism was step 3 and is likewise unnecessary at 3.8 min.

### Memory, honestly

The engine is still a **sibling** container and still outside the runner's
cgroup — that has not changed, and 4.97 GB remains the runner's own figure.
Two things did change:

* There is now **one** engine container per run instead of ~20,000
  short-lived ones, and `EngineSession.memory_bytes()` reads it. Soaked over
  2,400 runs it oscillates between 90 and 137 MiB and returns, with flat
  throughput and 6 cached schemas. So the unmeasured sibling is ~0.1 GB, not
  an unknown.
* `EngineImage(cpus=..., memory=...)`, and the environment variables
  `FHIR_SULO_ENGINE_CPUS` / `FHIR_SULO_ENGINE_MEMORY`, hold the engine to an
  explicit envelope. Agent 6 asked for this in `benchmarks/run.sh`'s comment;
  it is a seam they can set without editing Python.

`default_image()` also now returns a shared instance per (tag, cpus, memory),
so three map families mean one engine rather than three.

## 2. Two `graph_key` functions with different semantics

`engine.driver.graph_key` hashed four identity fields.
`store.graph_key` (DR-601) hashes thirteen, and the store **rejects** a run
record whose key does not recompute from the record's own fields — which is
what makes an archived correction verifiable. So `PipelineOutcome.run_record()`
produced records the store refused: correct of the store, useless of the
method.

Converged rather than documented. `engine.driver.graph_key` is **removed** — it
raises `NotImplementedError` naming the replacement, rather than being
deprecated, because a weaker function with the same name is how someone ships a
graph whose key does not mean what the store thinks it means.

The pipeline now computes the real key:

* `Pipeline.metadata` (`RunMetadata`) carries the run-level facts the key is a
  function of — SULO version, domain ontology version, policy version, engine
  build — filled from the policy bundle and the image digest, with
  `"unresolved:R1"` for the domain namespace the pilot has not decided.
  `GraphKeyInputs` refuses an empty string on the reasoning that "undecided"
  and "decided" must not hash to the same graph, and that rule now bites here
  usefully.
* `Pipeline.run_inputs(context)` builds the 13-field `RunInputs`;
  `TransformResult.output_graph_key` is `inputs.graph_key`.
* `PipelineOutcome.run_record()` delegates to
  `provenance.run_records.build_run_record`, which derives the key from the
  record's own fields.
* `pipeline.cli.batch_entry` takes `inputs.key_inputs().as_dict()` instead of
  rebuilding 13 fields by hand — which is how the batch and the run record
  could have disagreed about a key in the first place.

Verified: for a BP fixture, `transform.output_graph_key == record.output_graph_key`
and `store.graph_key(GraphKeyInputs.from_run_record(record)) == record.output_graph_key`.
`run_record()` output now loads.

## Consequences

- Gate 4's scale row passes with 3.9× headroom; the bottleneck is now SHACL
  and OWL reasoning, which are Agent 6's, not mapping.
- Any code calling `engine.driver.graph_key` breaks loudly and is told where
  to go. Nothing outside this package called it.
- A host process that uses the engine should let it close, or let the
  interpreter exit; `atexit` covers the ordinary case and stdin closure covers
  the rest.
- `reuse_process=False` still runs one container per call, and the recorded-
  fixture tests use it, so the one-shot bridges stay exercised rather than
  rotting behind the fast path.
