# DR-303 — The two host-side engine tools: schema-pair linter and materialization driver

**Status:** Decided and implemented
**Date:** 2026-09-29
**Gate:** 1 → binds Gates 2, 3, 4 and 5
**Implements:** DR-301 decision 3, CD-1, CD-2, DR-302
**Owner:** Agent 4

## What was built

| Tool | Entry point | Carries |
| --- | --- | --- |
| Schema-pair linter | `tools/shexmap-lint`, `fhir_sulo.engine.linter` | acceptance row "Mapping analysis" (CD-1) |
| Materialization driver | `fhir_sulo.engine.driver` | acceptance row "Deployability" (CD-2) |

Both sit on `fhir_sulo.engine.docker`, which runs the pinned image
`fhir-sulo/shexmap:1.0.0-alpha.33`, built from `tools/engine/Dockerfile` and the
lockfile DR-301 pinned.

## The rule both tools are shaped by

Every failure DR-301 found is **silent**. The engine does not warn, does not
write to stderr, and exits 0. So neither tool is allowed to warn about anything
it can prove: the linter fails the build, and the driver raises.

The corollary sets the division of labour, and it is not the obvious one:

> **The driver cannot catch nested repetition, and the linter cannot catch
> truncation.** Neither tool subsumes the other.

Two levels of repetition consume every binding, truncate nothing and report no
unbound variable — the values are all present and all attached to the wrong
group (`tests/engine/test_driver.py::TestNestedRepetitionIsNotCaughtHere`,
against a recorded engine response: 4 panels emitted for 2 source Observations,
one of them carrying the 09:15 timestamp with the 11:40 measurement). That is
why DR-302 is enforced at build time and could not have been a runtime check.

## Interfaces

### Linter

```python
from fhir_sulo.engine import lint_pair, check_contract
report = lint_pair(source_schema, target_schema, static_variables={...})
report.raise_for_status()          # SchemaPairLintError if any error finding
```

```
shexmap-lint SOURCE.shex TARGET.shex [--static NAME=VALUE] [--json]
shexmap-lint --dir maps/           # recursive: every **/source.shex + target.shex
exit 0 = no errors · 1 = errors · 2 = could not run
```

Findings. `SP0xx` fail the build; `SP1xx` do not. There is no flag to downgrade
an error.

| Code | Obligation | What the engine does instead |
| --- | --- | --- |
| SP001 | unbound variable | prunes the branch, emits a partial graph, exit 0 |
| SP002 | two repeating constraints on one path (DR-302) | mis-associates groups, drops members |
| SP003 | unknown Map function or undeclared prefix | deletes the enclosing shape |
| SP004 | Map annotation on a shape-valued **target** constraint | emits the IRI as a leaf, drops the sub-shape |
| SP005 | cycle in the target schema | unrolls to `maxCallDepth`, then kills the thread |
| SP006 | no start shape | `no shape given and no start in schema` |
| SP007 | dangling shape reference | `shape … not found`, at runtime |
| SP101 | source variable never read by the target | *(warning)* lowers inverse coverage |
| SP102 | cycle in the source schema | *(warning)* makes depth data-dependent |
| SP103 | unused static variable | *(warning)* |
| SP2xx | `check_contract`: the reviewed `MapContract` no longer matches its schemas | — |

Two details worth knowing before writing a map:

* **SP003 has two routes and both are silent.** The engine tries its variable
  pattern before its function pattern, so `id(v:code)` — which contains a colon
  — is read as a variable in an undeclared prefix `id(v`, while `skolemize(x)`
  reaches `extensions.lower` and throws `Unknown extension`. Which one an
  author hits depends only on whether their argument has a colon in it.
  `mapcode.py` transcribes both of the engine's regexes rather than
  approximating them, and both routes are in the negative set.
* **SP004 is target-only.** The same annotation in a *source* schema is correct
  and is how DR-302's decomposition binds its join key — `ok-decomp-a` lints
  clean and proves it.

`check_contract(contract, source, target)` additionally confirms a reviewed
`MapContract` still describes the schemas it names. `MapContract.static_analysis_passed`
is a boolean an author could simply set; this is what makes setting it honest.

### Driver

```python
from fhir_sulo.engine import PassSpec, Guards, materialize, to_transform_result
result = materialize([PassSpec(...), ...], guards=Guards())
transform = to_transform_result(result, map_id=..., pairing_hash=..., ...)
```

`Guards` are **ours**, set explicitly on every call, never inherited:
`max_accepts=100_000`, `max_repeat=100_000`, `max_steps=1e8`,
`explore_steps=1e8`, `max_call_depth=50`. `run-pass.js` refuses a request that
omits any of them, so an engine default cannot leak in through a forgotten
field.

Fail-fast. Each exception is a DR-301 finding where the engine's CLI exits 0:

| Exception | Trigger |
| --- | --- |
| `SourceValidationFailure` | source graph does not conform |
| `UnboundVariables` | `lastReport.unboundVariables` non-empty |
| `ExplorationTruncated` | `lastReport.explorationTruncated` |
| `AcceptCeilingReached` | accepts hit `max_accepts` — DR-301 B2, the 19-of-60 truncation |
| `BindingsNotConsumed` | a source binding the target never read |
| `UntracedQuad` | a quad with no target-schema constraint behind it |

`BindingsNotConsumed` earns its place: the no-colon route of SP003 produces an
**empty** `unboundVariables` list, so binding coverage is the only runtime
signal that the shape was deleted.

Coverage is computed over **distinct origins in the binding tree**, not over
frame bindings. `normalizeBindingTree` distributes a variable that sits above a
repetition into every frame below it, so a patient name appears N times and is
consumed once; counting raw frame bindings would report a correct map as lossy.

## The driver emits no triple of its own — enforced, not asserted

DR-302 asked for this to be mechanical. It is:

1. `run-pass.js` numbers every `TripleConstraint` in the target schema and tags
   each emitted quad with the id of the one that produced it.
2. `DriverResult.untraced_quads()` is empty only when every quad in the union
   names a constraint the pass's target schema declared.
3. `to_transform_result` refuses to build a `TransformResult` otherwise — and
   `TransformResult` itself refuses a `MAPPED` result whose quads are not all
   covered by lineage. Two independent gates, one of them frozen at Gate 0.

`tests/engine/test_driver.py::TestDriverEmitsNoTripleOfItsOwn` asserts this
against the **three-pass union**, where a host-built triple would be easiest to
hide, and includes a forged quad to prove the guard can fail.

The one place the host touches a term is blank-node relabelling, which the
union must do because every materialization restarts its counter at `_:tm0`
(DR-301 §4d — it merged unrelated nodes in the first version of probe 10). That
is proved inert: the multiset of quad signatures, with blank node labels masked
out, is identical before and after the union.

## Testing strategy

Schemas are parsed by the **engine's own parser**, never by a Python
reimplementation, so the linter cannot disagree with the engine about what a
schema says. The parsed ShExJ and a set of real engine responses are committed
under `tests/engine/fixtures/`, which lets 66 linter and driver tests run in CI
with no Docker. `test_engine_live.py` re-parses and re-runs everything against
the live image and fails on drift, so an engine bump announces itself rather
than silently invalidating the recordings.

The negative schemas the acceptance row requires are in
`tests/engine/schemas/neg-*`. Each is a pair the engine **accepts and then
mishandles in silence**; the header comment on each records what the engine
actually does with it. `TestTheLinterIsNotCryingWolf` checks that claim against
the live engine, so a build-time refusal is never merely asserted to be
proportionate.

| Command | Docker | What it covers |
| --- | --- | --- |
| `make engine-tests` | no | linter and driver rules (66 tests) |
| `make engine-live` | yes | fixture drift, linter-vs-engine, driver end to end (19 tests) |
| `make lint-schemas` | yes | every pair under `maps/`; fails the build |
| `make engine-probes` | yes | the original DR-301 capability probes |

## Consequences

- Agent 3 runs `make lint-schemas` before proposing any pair; `maps/**/source.shex`
  plus `target.shex` is the layout the linter discovers.
- Agent 6 drives `fhir_sulo.engine.driver`, not `shexmap-materialize`, and gets
  `provenance[]`/`frameOrigins` through `DriverResult` and `QuadLineage`.
- `RunRecord.engine_build` should be `EngineImage.build_id()`, which is the
  image content id, not the tag — a tag can be rebuilt.
- `DriverResult.content_digest()` is deterministic but **not**
  isomorphism-invariant: two structurally identical graphs from different pass
  decompositions digest differently. Gate 4's "unchanged reprocessing changes
  no triples" is satisfied by it; a cross-decomposition comparison is not, and
  would need real canonicalisation.

## One thing for the integration lead

`TransformResult.__post_init__` guards lineage coverage with:

```python
if self.status is TransformStatus.MAPPED and self.lineage:
```

The trailing `and self.lineage` means the check runs only when lineage is
already present, so a `MAPPED` result carrying quads and **no lineage at all**
is accepted and reports `is_loadable` — the exact case the guard exists to
stop. Pinned by `tests/engine/test_driver.py::TestFrozenContractGap`, which
also shows the driver does not rely on it: `to_transform_result` refuses an
untraced quad on its own, before the contract is ever constructed.

The fix is to delete three words. It is not made here because the four
interfaces are frozen and changing one is the integration lead's call
(plan §6 rule 1). When it is made, that test class should be deleted with it.

## Post-review corrections

Seven defects found and fixed while reviewing the first implementation. Five of
them were **false negatives** — the tool would have passed something bad — which
is the only failure direction that matters for a gate whose job is to catch
silent faults. Recorded because each one is a trap the next person could set
again.

| Where | Defect | Why it mattered |
| --- | --- | --- |
| `shexj.walk_paths` | repetition counted as a boolean per arc, so `(:x .*)*` and two nested repeating groups both scored 1 | DR-302 violations would have linted clean; now `repeat_depth` counts group nesting plus the constraint's own |
| `shexj.Cycle` | `through_repetition` indexed `steps` by a *stack* length — arithmetic over two different sequences | unused, and wrong; removed rather than left for someone to trust |
| `shexj.walk_paths` | no breadth bound; shape references form a DAG, so paths are exponential in shape count | a build gate that hangs, or worse analyses a prefix and passes; now `SchemaTooLarge` → SP008 |
| `mapcode` | Python `$` matches before a trailing newline, JavaScript's does not | `" v:name \n"` would lint as a valid variable while the engine prunes the branch; now `\Z` |
| `mapcode` | `<>` yielded no variable and no problem | binds the empty name, never binds, shape deleted in silence |
| `rdfterms` | control characters emitted raw | invalid N-Triples: a corrupt graph rather than a rejected one, and clinical free text really does carry them |
| `driver` | `union_passes` kept only the first pass's binding tree | a decomposed map's acceptance tuples were unreachable from `TransformResult.binding_tree` — the check would have inspected the skeleton only |

Two further places now refuse instead of guessing: sibling binding-tree frames
that disagree about a variable, and a declared key variable an iteration does
not bind (which would key every iteration as `('',)` and undo the reason
`RepetitionScope` demands key variables at all).

`mapcode` also now explains the trap rather than only reporting it: a code like
`regex(/(?<v:a>x)/)` with no space in its argument matches the engine's
*variable* pattern first and never reaches the function dispatcher. Flagging it
is agreement with the engine, not strictness — but "prefix `regex(/(?<v` is not
declared" is not a message anyone can act on, so the finding now says what
actually happened.
