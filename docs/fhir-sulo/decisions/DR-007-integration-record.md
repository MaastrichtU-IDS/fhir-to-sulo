# DR-007 — Integration record: merges, defects found, and open debt

**Status:** Decided / recorded (Agent 1, integration lead)
**Date:** 2026-09-29
**Gate:** 0 → 4

All five agent branches are merged into `integration/gate0-1`. Every agent's headline claim was
re-verified by the lead through fault injection rather than accepted on report.

## 1. Defects found *in the integration*, not in any one branch

These are the merge's own findings. None was visible from inside a single worktree.

| # | Defect | Consequence if unfixed |
| --- | --- | --- |
| 1 | `unittest discover` does not descend into non-package subdirectories | 122 of Agent 5's tests invisible to CI; `check_mock_services` passed on two directories existing |
| 2 | `TransformResult` lineage guard keyed on `self.lineage` | a `MAPPED` result with quads and **no** lineage validated and reported `is_loadable` — the exact case the guard existed to stop |
| 3 | Agent 4 and Agent 6 both wrote `tests/*/support.py`; `tests/` was not a package | six integration modules failed to collect; one `support` bound for both suites |
| 4 | `RunRecord` had no `renderer_id` (IR-601) | a renderer change was invisible to the graph key: reprocessing after one reported `unchanged` while triples could differ |
| 5 | Agent 5's determinism AST guard used `rglob` over all of `src/` | at integration its scope silently widened and it began flagging legitimate constructs — `RunRecord.activity_time` (which *must* be wall-clock) and the reasoner's temp-file uuids |
| 6 | `make clean` could not reach the bytecode cache | on this machine `sys.pycache_prefix` is `~/Library/Caches/com.apple.python`, i.e. **outside the tree**; a stale entry survived an edit and produced a module whose runtime behaviour contradicted its own source |
| 7 | Gate 2/3 map suites skipped in CI | the whole Gate 2/3 suite never ran on a clean runner; a skip is not a pass |

Fixes: (1) pytest is the authoritative runner, stdlib path kept green, both run in CI.
(2) keyed on `target_quads`; contract **0.2.0**. (3) `tests/` and `tests/integration/` are
packages, imports made relative. (4) `RunRecord.renderer_id` added and folded into the graph
key's content fields; contract **0.3.0**. (5) the guard is now two explicit tiers — a *declared*
key-path module list (no clocks, uuids, randomness) and an all-of-`src` ban on the builtin
`hash()` — plus a meta-test that the declared list names real files, so it cannot silently
shrink to nothing. (6) `make clean` resolves `sys.pycache_prefix` and clears it. (7) a Docker CI
job runs `engine-live`, `lint-schemas`, and the map and integration suites with
`FHIR_SULO_REQUIRE_ENGINE=1`.

## 2. Verification performed by the lead

Each was injected, observed to fail, and reverted.

| Claim | Injection | Result |
| --- | --- | --- |
| Agent 5 keying is deterministic | per-process salt into `policy/canonical.py::digest()` | 2 failures, incl. the CI-visible stdlib mirror |
| Agent 2 renderer preserves fidelity | decimal trailing-zero stripping | 3 failures on `FhirNumber('55.0') != FhirNumber('55')` |
| Agent 4's linter honours its exit contract | ran the negative pairs directly | exit 1 on errors, 0 on clean — checked because exit-0-on-failure is what got the engine CLI banned |
| The driver cannot catch nested repetition | read the live-engine test | confirmed: bindings all consumed, no unbound variables, panel count ≠ 2 |
| Agent 6's reasoner verification | ran HermiT and ELK through the same path | HermiT entails and refutes; ELK does neither, silently — the negative control is real |
| Agent 6's benchmark | re-ran `benchmarks/run.sh` from clean | 168.58 s, 1.44 GB vs targets of 15 min / 6 GB |
| Agent 3's BP multiset | swapped the systolic/diastolic LOINC codes **and rehashed**, so only semantics could catch it | 8 failures incl. `test_the_concept_note_multiset_is_exactly_right` |
| The canonicaliser drift guard | NFC → NFD in `store/canonical.py` | 3 failures |

One injection was a **no-op** and is recorded as such: loosening the diastolic constraint to also
accept the systolic code changed nothing, because the fixture data still forces the correct
assignment. It is evidence the design is robust, not evidence about the guard.

## 3. Decisions taken

- **Entity IRI style `scoped-slug`** (DR-005) — readable enough for a human to review an
  expected graph, without `legacy-concept-note`'s built-in cross-scope rejection.
- **`renderer_id` joins the graph key** (IR-601). Anything that can change an emitted triple
  belongs in the key; a renderer change must re-key rather than report `unchanged`.
- **`make gate1` requires Docker.** A gate that can pass without running the engine is not
  evidence. `make contracts-stdlib` remains the zero-dependency path.
- **`gate-check.py` enforces gate ordering** (plan §6 rule 5): a later gate reports `HELD`, never
  `PASSED`, while an earlier one is blocked.
- **pytest pinned to 8.3.5**, resolving the Agent 2 / Agent 5 add/add conflict; Agent 5's suite
  passes unchanged on it. `rdflib` resolved to 7.1.4 (dev) over 7.1.1 (runtime).
- **HL7 oracle vendored** (DR-006) with a CC0 provenance note, rather than making four
  conformance tests network-dependent.

## 4. Open debt, with owners

| Ref | Item | Owner | Blocking? |
| --- | --- | --- | --- |
| IR-602 | `policy/canonical.py` and `store/canonical.py` are independent implementations of the same rules. They **currently agree** — verified over a corpus exercising NFC folding, key ordering, nesting and float rejection, with a test that fails on drift (proved by an NFC→NFD injection). Converging them into one module is the right end state. | Agents 5 + 6 | no — drift now fails CI |
| IR-603 | **Node identity is owned by two components.** Agent 5's service mints person and quality IRIs; result, record, role, interval and time IRIs are minted from rules in Agent 3's map manifests. One component should own node identity. | to assign | no, but it will bite at Gate 5 |
| IR-604 | Contained-reference scoping (`#p-inline` must not merge across containers) is applied by Agent 3 and duplicated in Agent 2's mock. It belongs inside the identity service, not in every caller. | Agent 5 | no |
| CD-4 | Lineage reaches the binding tree, not the source triple. | Agent 6 | no — scoped, not glossed |
| DR-201 §5.1 | **`Encounter.participant` is capped at cardinality 1.** A second participant fails loudly. Not a repetition problem: each participant needs distinct minted role and holder IRIs, and `staticVars` are global to a materialization. DR-302's decomposition does not rescue it, because a FHIR participant is a blank node with no source IRI to root at. **This recurs for any repeated group whose members need distinct minted IRIs, including Gate 5's `MedicationAdministration.dosage`.** | Agent 3 + whoever scopes Gate 5 | not for Gates 0–4 |

## 5. Gate status at the close of integration

```
Gate 0 BLOCKED  (8 pass, 0 fail, 1 manual; own conditions BLOCKED)
Gate 1 HELD     (6 pass, 0 fail, 0 manual; own conditions PASS)
Gate 2 HELD     (5 pass, 0 fail, 0 manual; own conditions PASS)
Gate 3 HELD     (4 pass, 0 fail, 0 manual; own conditions PASS)
Gate 4 HELD     (5 pass, 0 fail, 0 manual; own conditions PASS)
```

Every gate's engineering conditions pass. **Gate 0's single remaining item is the human
reviewer's sign-off**, and by plan §6 rule 5 every later gate is correctly `HELD` behind it.
No gate is reported as passed, and nothing in `REVIEW-REQUEST.md` (12 items) is marked approved.

---

# Addendum — independent review, 2026-09-29

An independent reviewer with no part in building the pilot attacked the branch. It found two
blockers and six majors. **Every finding reproduced.** Three of them contradicted claims this
record made, so this section corrects them rather than editing the text above.

## The three claims in this record that were wrong

**1. "The BP multiset is verified against the live engine" — the verification tested the wrong
artifact.** The lead's fault injection swapped the systolic and diastolic LOINC codes in the
**source** schema, which changes source bindings. The acceptance test built its `BindingNode`s
from `_sourceBindings`, so it was asserting over extraction, never over the emitted graph.
Injecting into the **target** schema instead:

```
bp-target.v1.shex: diastolic node emits %Map:{ v:sysValue %}, rehashed
→ BPTupleMultiset 20 passed, incl. test_the_concept_note_multiset_is_exactly_right
→ emitted: <bp-diastolic-result-bp-1> sulo:hasValue "120"^^xsd:decimal
```

A clinically wrong graph with the headline Gate 3 test green. Fixed in DR-203: the multiset is
now read out of the emitted graph, keyed on the graph's own `prov:wasDerivedFrom`, with the slot
decided by the class of the quality each quantity `refersTo`. Both injections now fail 10 tests.

The generalisable rule, which applies to every fault injection in this record:

> An acceptance condition is asserted on the emitted target graph. **A fault injection only
> demonstrates coverage of the artifact it perturbs** — injecting into the source schema says
> nothing about whether the target schema is checked.

**2. "A Docker CI job runs `engine-live`, `lint-schemas` and the map suites" — `lint-schemas`
had never passed.** `make lint-schemas` exited 2 with "no schema pairs under maps": the linter
discovered only files named `source.shex`/`target.shex`, while the shipped pairs are
`<family>-source.v1.shex`. The CI job would have failed on first run. This record asserted it
ran without anyone running it. Worse, when pointed at the pairs directly the linter walked only
from `start`, leaving 9 of BP's 10 root shapes unanalysed. Fixed in DR-304: discovery follows
the shipped naming, and the linter now lints once per declared pass — 25 root shapes across the
three maps. `static_analysis_passed` is now `true` in all three contracts, and its test asserts
the claim **and** runs the linter, so the two cannot drift apart.

**3. Three tests were deleted and not noticed.** The lead's rewrite of the static determinism
guard replaced everything from one function to end-of-file, dropping
`test_candidate_order_does_not_affect_the_key`,
`test_repeated_reference_resolves_to_one_person` and
`test_unicode_equivalent_ids_do_not_split_one_person`. Nothing replaced them; no record
mentioned it. Restored verbatim; all three still pass.

## The other blocker: the pipeline was three islands

Nothing ran FHIR JSON → maps → store. The production driver was imported only by its own tests;
the production maps ran through a `run-map.js` whose own header called itself temporary; the
store consumed a batch format whose only producer was the synthetic benchmark generator. So plan
§8's "an operator can run a batch without editing code" was not met for FHIR input.

Fixed (DR-304). `run-map.js` is deleted, `src/fhir_sulo/pipeline/` is the missing middle, and
the "host emits no triple of its own" guard now runs over the **real** maps rather than toy
pairs. Verified by the lead:

```
$ python -m fhir_sulo.pipeline.cli batch --family bp --quality-mode per-observation \
    --out batch.jsonl --load store/ fixtures/r4/bp/bp-two-panels/bp-{1,2}.json
$ python -m fhir_sulo.store.cli inspect --state store/state.json
source_versions 2 · 2 subjects, each with a deterministic graph key
```

## Defects found while fixing the defects

- **The suite was not reliable from clean.** `make clean && pytest tests` gave 22 failures, then
  2, then 0. Not cold-cache — the maps suite alone passed from clean. Causes, found by Agent 3:
  the job document was `docker cp`'d to a fixed path and could be read by the *previous* call's
  runner, and the container tree was shared across processes. Both fixed; the job now goes in on
  stdin. **CI always runs from clean, so this would have been a permanently red pipeline.**
- **The engine image tag was shared mutable state across worktrees** (CD-5). `ensure_built()`
  no-ops when the tag exists, and the worktrees share one Docker daemon, so whoever built last
  won and everyone else silently ran an image not matching their tree. The tag now carries a
  hash of the build context.
- **A function-local `from support import`** survived two sweeps that only matched module-level
  imports, binding the wrong suite's helpers. Now guarded by
  `tests/contracts/test_repo_hygiene.py`, which also asserts the collision it guards against
  still exists, so the guard is removed deliberately rather than left as cargo cult.
- **`make venv` installed only the dev requirements**, so 20 validation tests skipped locally
  while CI ran them. A local run that silently covers less than CI is worse than one that fails.

## Gate-check defects, all self-inflicted

The tool that reports gate status had six weak or broken checks. All were mine.

| Defect | Now |
| --- | --- |
| `--report` forced exit 0, so the CI gate job could never fail | exit status reflects the gates |
| `check_bp_multiset_live` defined, never wired — dead code reading as coverage | removed; the condition runs the real suites |
| BP pairing check parsed "PASS 3" from this record's prose, then grepped the test tree for the substrings "120"/"80"/"105"/"70" (six files matched) | runs the engine probe **and** the map suite |
| Gate 1 determinism was a regex for "PASS 4a" | runs the byte-identical-across-runs test |
| "Expected pivot tuples committed" was a filename regex that passed on empty files | requires each artifact to parse and declare tuples |
| `check_benchmark` read only `passed: true` | verifies resource count, both limits, and that rendering and materialization are among the stages |

`tests/contracts/test_gate_check_itself.py` now asserts the structural ones: no condition may
reference an undefined check, no check may be dead code, `--report` may not short-circuit, a
raising check must report FAIL, and the reviewer sign-off must report MANUAL while the review is
open.

## What the review found solid

Store correction semantics (a broken `_retire` produced 8 failures), the ELK negative control,
the round-trip mutation suite, pairing-hash tamper detection, the determinism keying path, and —
the question that mattered most — **no host-side triple construction**: every emitted triple
comes from a target schema, with the host supplying root IRIs and static variables and unioning
passes. Git history was clean: no threshold, expected graph or shape had moved.

## Still open after the review

- **M3 / Gate 4 scale.** The benchmark measured keying, provenance, SHACL and reasoning with no
  rendering and no mapping in it. DR-604 has been amended to say the Gate 4 scale row is **not
  satisfied**. Now unblocked by the composed pipeline; being re-measured honestly.
- **R6 has no OWL guard, contrary to DR-603.** Measured with HermiT: a person typed
  `sulo:SpatialObject` alongside a Quality or Role is inconsistent, but a person typed
  `sulo:Object` — which is what the maps emit — is **consistent**, because
  `Quality ⊑ Feature ⊑ Object`. SHACL still catches it, so nothing reaches the store, but the
  acceptance row saying "an OWL reasoner checks consistency" leans on a guard that is not there.
  Recorded as input to R6; it does not answer it.
- **No two fixtures are two versions of the same resource**, so Gate 4's correction row rests
  partly on a hand-edited literal. An `egfr-corrected` fixture is requested.

---

# Addendum 2 — Gate 4 scale, measured and missed

The review's M3 said the benchmark excluded the transformation. That is fixed: it now runs
10,000 synthetic FHIR R4 resources through ingest, RDF rendering, the reviewed maps, the pinned
engine, store, SHACL and HermiT. **The result is a failure, recorded as one.**

| Gate 4 target | Measured | |
| --- | --- | --- |
| ≤ 15 min | **78.1 min** (4,685.11 s) | **missed, 5.2×** |
| peak memory < 6 GB | 5.68 GB | met, 5% headroom |
| no unexpected mapping failures | 9,510 mapped, 490 not, all 490 explained | met |

The corpus was not shrunk and the target was not revised. Plan §4 permits revision "only by an
explicit performance decision backed by measured profiles"; this is the profile, and it argues
for fixing the engine invocation rather than moving the target.

## The bottleneck is invocation overhead, not mapping

`materialize` is 95.9% of the run at 0.472 s per mapped resource:

- a bare `docker run --rm -i <engine> node -e 0` costs **0.169 s**
- there are **two** engine invocations per resource (bind pass, materialize pass)
- so **container start-up is ≈0.339 s, or 72% of the per-resource cost**

Cost is flat across families — eGFR 0.503 s (21 quads), BP 0.552 s (34 quads), Encounter
0.519 s (29 quads). BP's ten-pass map emits 62% more triples in the same time, which is what
rules out schema work as the cause. The engine's actual materialization is **0.030 ms/resource**
(`engine_bench` Part A), four orders of magnitude below what is being paid.

Fix in progress with Agent 4, in this order: a long-lived container or persistent Node process
(start-up alone ≈22 min, conservative because schemas are still re-parsed per resource), then
batching resources per invocation (safe under DR-302 — maps are resource-rooted and nothing
crosses resources), then parallelism, which is a legitimate 4× only *after* the first two.

## Two results that should not be read as part of the miss

- **"No unexpected mapping failures" was previously unaskable and is now satisfied.** All 490
  non-mapped resources are policy-declared outcomes with reasons from the pinned status policy
  (262 `dataAbsentReason`, 228 `entered-in-error`). Zero render failures, zero engine exceptions.
- **The memory row is a near miss, not comfort.** The cgroup peak is monotonic, so the stage
  column is a running high-water mark: 3.3 GB through materialize/store/provenance, 4.05 GB
  after SHACL, and OWL reasoning adds the last 1.6 GB to finish 0.32 GB under the limit. That
  consumer scales with **encounter count**, which is 19.9% of this corpus. More encounters, or a
  larger reasoning batch, would exceed 6 GB.

## Measurement caveat, stated rather than buried

The `--cpus=4 --memory=8g` runner constraint **does not reach the engine containers**: they are
siblings outside the benchmark's cgroup, because `EngineImage` hardcodes its `docker run`
arguments. This makes the time a **lower bound** — so the miss is conservative — and the
5.68 GB an **underestimate**, which matters more given the headroom.

## Also fixed here

`requirements-dev.txt` and `requirements-runtime.txt` pinned **different** rdflib versions
(7.1.4 and 7.1.1) while CI installs both in a single `pip install`. Aligned to 7.1.4.

## Resolution — the profile was acted on, and the row now passes

The measurement above is kept because it is the evidence that justified the fix, not because
it is the current state. Agent 4 acted on the diagnosis (DR-305).

| Stage | Before | After | |
| --- | ---: | ---: | ---: |
| **materialize** | 4,491.5 s | **46.0 s** | **97.7×** |
| shacl validation | 85.4 s | 85.6 s | — |
| owl reasoning (HermiT) | 104.2 s | 93.3 s | 1.1× |
| **TOTAL** | **4,685.1 s (78.1 min)** | **228.4 s (3.8 min)** | **20.5×** |
| peak memory | 5.68 GB | **4.97 GB** | |

| Gate 4 row | Target | Result |
| --- | --- | --- |
| time | ≤ 15 min | **PASS** — 3.8 min, 3.9× headroom |
| memory | < 6 GB | **PASS** — 4.97 GB, 17% headroom (was 5%) |
| no unexpected mapping failures | — | **PASS** |

**Reproduced independently by the lead**, not accepted on report: `./benchmarks/run.sh` →
**235.02 s (3.9 min), 5.17 GB peak, VERDICT PASS**, with the same failure categories
(262 `dataAbsentReason`, 228 `entered-in-error`). Slightly above Agent 4's figures and within
run-to-run noise; both pass.

**Output is unchanged**, which is the claim that mattered: 9,510 mapped, 490 not, 261,236
target triples — the same three numbers as the 78-minute run. Not inferred from the totals:
`TestResidentOutputEqualsOneShot` runs each family through a resident *and* a one-shot engine
and requires identical quads, lineage and graph key, with interleaved families and ten repeats
through one process. A schema cache and a reused process are exactly what could make the
second answer differ from the first.

### What was done, and what was deliberately not

Only step 1. The engine stays resident behind a newline-delimited JSON protocol on stdin;
schemas are parsed once per `(text, baseIRI)` rather than once per resource. Both constraints
held literally: the transport, `docker run --rm -i` and the absence of a bind mount are
unchanged — only the container's lifetime changed, so the colima trap is untouched — and the
container is **anonymous**, with no `--name`, owned by one host process and dying with it. A
*named* long-lived container is precisely the CD-5 shape and was avoided on purpose.

Step 2 (batching) was **built, measured and left disabled**: a resident round trip costs 0.28 ms
against 42 ms of real work, so the overhead it would amortise is 1.3% of the cost. Wiring it in
would complicate the path that carries the no-host-triple guard in exchange for a percent.
Step 3 (parallelism) is moot at 3.8 min.

### The bottleneck moved

`materialize` is now 20% of the run. SHACL (85.6 s) and HermiT (93.3 s) dominate both time and
the memory ceiling: the materialize stage's own cgroup peak is 3.27 GB, while the run's 4.97 GB
peak arrives during reasoning. **The unmeasured sibling engine container is now quantified at
about 0.1 GB** — soaked over 2,400 runs it oscillates 90–137 MiB and returns, with a 150-run
leak guard in the suite. So CD-4's caveat about the runner cgroup not reaching the engine still
stands, but the unknown it left is now small and measured rather than open.

### One defect this surfaced

`./benchmarks/run.sh` did not pass `--strictness`, which Agent 6 had correctly made **required**
so that no run can silently pick an answer to R5. The wrapper was never updated, so the
documented command failed outright. Fixed: `run.sh` supplies
`--strictness concept-note-literal --quality-mode per-observation` by default, both overridable
from the command line, both named in the report. Naming them is the point — it is not an answer
to R5 or R2.
