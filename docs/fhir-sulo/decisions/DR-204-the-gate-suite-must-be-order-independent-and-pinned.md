# DR-204 — The Gate 2/3 suite must pass from clean, in any order, on the pinned image

**Status:** Two defects found in review, both fixed; the guards are permanent
**Date:** 2026-09-29
**Gate:** 2 / 3
**Found by:** the integration lead
**Owner of the defects:** Agent 3 (harness)
**Related:** DR-203 (the acceptance check was on the wrong artifact), CD-2, DR-301

Two more ways the Gate 2/3 evidence could have been worthless, neither of them
about the maps themselves.

## 1. The suite was order-dependent and failed from clean

Observed:

```
make clean && pytest tests -q   ->  22 failed, 622 passed
pytest tests -q                 ->   2 failed, 642 passed
pytest tests -q                 ->       644 passed
```

while `make clean && pytest tests/contracts/maps -q` alone passed. **CI always
runs from clean**, so a suite that is only green on a warm tree is not a gate.

The first failure was `IdentityUnavailable: incomplete-key-inputs ... empty key
input field: source_resource_version_id`, which looks like an identity bug and
is not one: it is what you get when the binding tree came from a resource the
caller did not ask about.

Two causes, both in the harness, both now impossible:

- **The job document was raced.** The job was `docker cp`'d to a fixed
  `/w/job.json` and then read by a separate `docker exec`. `docker cp` returns
  once the daemon has accepted the archive, so a run could read the *previous*
  call's job and materialize the wrong fixture. That is where the empty
  `versionId` came from. Three consecutive runs of the BP suite gave three
  different failure sets.
- **The container tree was shared between processes.** The repository was
  copied into one long-lived container under a shared path, and
  `fixtures/expected/build.py` runs as a subprocess from one of the tests and
  re-synced that same path. A parent that had already synced went on trusting
  a tree another process had torn down and rebuilt. The non-atomic `rm -rf`
  then `cp` left a window in which a run saw a missing fixture.

Both are gone with the repoint onto Agent 4's driver (below), which passes
schema and graph text on stdin to `docker run --rm` and copies nothing.

**Guard:** `tests/contracts/maps/test_order_independence.py` re-runs the whole
maps suite in a different order in a fresh process and fails if the outcome
differs. Reversed by default, so a failure is reproducible;
`FHIR_SULO_MAPS_ORDER_SEED` shuffles instead, and CI can vary it per build.
It earned its place immediately: it caught three further order-dependent
tests, two of which were ones I had just written.

## 2. The maps were not tested against the pinned image

The harness ran plain `node:20-bookworm-slim` and did `npm ci` at test time.
Agent 4's digest-built `fhir-sulo/shexmap:…` is what DR-301 and CD-2 pin, and
it was **not** what produced the Gate 2/3 evidence. The pin therefore did not
cover the tests that matter most, and a divergence between the two would have
been invisible.

Resolved by adopting Agent 4's driver rather than duplicating the pin: the
harness is now a thin adapter onto `fhir_sulo.engine.maprun.MapJob`, the
test-only `run-map.js` is deleted, and every call runs the production bridge
in the pinned image.

Worth recording: the goldens in `fixtures/expected/` reproduce **byte for
byte** across the move from the floating base to the digest-pinned one, so
this closed a real gap in the evidence without changing any output.

**Guards:** `HarnessCarriesNoStateBetweenRuns` asserts the image is the pinned
*content-addressed* tag (a bare version tag is shared mutable state between
worktrees — Agent 4's point, and correct), that its build id is recordable for
`RunRecord.engine_build`, that every engine call is `docker run --rm` with no
`--name`, and that the harness creates no container of its own.

## The rule

> **Evidence for a gate has to be reproducible from nothing.** From a clean
> tree, in any order, on the pinned image, with no container and no cached
> directory surviving between runs.

Everything a green run depends on must be either committed or built from
something committed. A container that has been up for four hours is state, and
state that nobody declared is state nobody checked.

## An instance of the rule catching me

The first version of `test_no_long_lived_container_is_left_behind` listed the
daemon's containers and asserted none matched the engine image. It passed
alone and failed in a full-suite run, because several agent worktrees share
one Docker daemon and other suites run engine calls concurrently — so the test
was itself order-dependent, in exactly the way it existed to prevent. It now
asserts how the driver invokes `docker` (`--rm`, no `--name`, no `docker cp`)
rather than what the daemon happens to contain.

## Two failures in other agents' files, reported not fixed

Found by running the full suite from clean three times; both reproduce every
time and neither is caused by the maps.

- `tests/engine/test_driver.py::TestNestedRepetitionIsNotCaughtHere::test_the_linter_catches_what_the_driver_cannot`
  — `from support import load_pair` raises `ImportError` in a full-suite run.
  There are two `support.py` modules, `tests/engine/support.py` and
  `tests/integration/support.py`, and which one wins depends on which
  directory pytest imported first. Passes alone. **Agent 4.**
- `tests/integration/test_reasoning_pro.py::R6EvidenceThePersonClassChoiceHasConsequences::test_the_shapes_catch_it_even_though_the_reasoner_does_not`
  — `MissingDependencyError` from `validation/shapes_check.py`. This one fails
  **alone** as well: its twenty sibling tests skip with "needs the pinned
  environment", and this one does not. **Agent 6.**
