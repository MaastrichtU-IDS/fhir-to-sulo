# Gate 1 engine spike — ShEx.js ShExMap

**Date:** 2026-09-29 · **Agent:** 4 (engine and portability) · **Verdict:** **CONDITIONAL GO**

ShExMap works, and works well, inside one specific envelope. Outside it, it does
not fail — it produces a wrong graph, exits 0, and says nothing. Both halves of
that sentence are load-bearing for the pilot.

## Headline

| | |
|---|---|
| **Works** | one level of repetition, arbitrary structural nesting, order-independent, deterministic, bidirectional, with per-quad lineage |
| **Does not work** | **two or more levels of repetition** (groups mis-associated, data lost) |
| **Booby trap** | the shipped CLI **silently truncates any repetition to 19 items** |
| **Absent** | `id()` / minted target IRIs; a static checker; non-zero exit on failure |

Three of these are silent. Nothing in the default CLI path tells you the output
is wrong.

## Environment

No node/npm on the host; colima shares only the VM owner's home, so bind mounts
into the scratchpad do **not** work. Everything runs in a container fed by
`docker cp`. `run.sh` does this; `--keep` reuses the container.

```
docker image: node:20-bookworm-slim
              sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0
node v20.20.2, npm 10.8.2
```

## Recommended pinned engine configuration

```jsonc
// package.json — install succeeds cleanly, 244 packages, no build step
{ "dependencies": {
    "shex":                    "1.0.0-alpha.33",
    "@shexjs/extension-map":   "1.0.0-alpha.33" } }
```

```
shex                    1.0.0-alpha.33  sha512-/tm9ZF4yoWROfcX/ayo6MmgYSklPOEeYjuKHM560g9RMJFfwQ90UGBze66v6R7owsWbnlx0nnZhno8Mr75EqQA==
@shexjs/extension-map   1.0.0-alpha.33  sha512-5FHkEoCUas9RCMGeJtXS68KhdphYBTuXkupJLYxjUE7MBIi92yCjk5tsYr1bGi0sHIQeih1KMsd9a1Xr6BuYwA==
@shexjs/term            1.0.0-alpha.29  (hoisted by ^1.0.0-alpha.28)
n3                      2.7.12
```

Full resolved tree with integrity hashes: `package-lock.json` (245 packages).
No git-repo fallback was needed — the npm release is functional.

**But: do not drive it from `shexmap-materialize`.** The CLI hard-codes the
search guards and discards the diagnostics. The supported configuration is the
programmatic API:

```js
const Mapper = require("@shexjs/extension-map")({rdfjs: N3, Validator: {}});
const m = new Mapper.ThreadedMaterializer(targetSchema, {
  staticVars: {...},
  maxAccepts: 1e6,        // MANDATORY — default 20 truncates output to 19 items
  maxRepeat:  1e6,        // default 50
  maxSteps:   1e9,        // default 1e6
  exploreSteps: 1e9,      // default 1e4
});
const quads = m.materialize(bindingTree, rootIri);
// then ALWAYS inspect: m.lastReport, m.provenance, m.frameOrigins, m.accepts
```

Validation (the binding-extraction half) is fine from the CLI:
`shex-validate --extension @shexjs/extension-map` exits 1 on failure and emits
parseable JSON.

---

## 1. Install & surface — **PASS**

```
$ docker exec shexprobe sh -c 'cd /w && npm install --no-audit --no-fund'
added 244 packages in 11s
```

Binaries that land in `node_modules/.bin` (shex-related):

```
dctap-to-json  dctap-to-shexj  json-to-shex  shex-debug  shex-partition
shex-serve  shex-to-json  shex-validate  shexmap-debug  shexmap-materialize
```

Note what is **not** there: no `shexmap-check`, no `shexmap-validate`, no
`shex-materialize` (it is `shexmap-materialize`, from `@shexjs/extension-map`,
whose `bin` entry is `bin/materialize`).

Programmatic API (`probes/p01-surface/`):

```
shex (meta package) exports: EditorServices, Engines, Extensions, Loader,
  NeighborhoodApi, Neighborhoods, NodeLoader, Parser, RdfJsDb, SemActOverlay,
  ShapeMap, ShapePathQuery, Term, Util, Validator, ValidatorApi, Visitor, Writer

require("@shexjs/extension-map") is a FACTORY: ({rdfjs, Validator}) => {
  MaterializationError, MaterializerDebugger, ThreadedMaterializer, done,
  extension, extensions, materializer, register, tripleConstraints, url, utils }

require("@shexjs/extension-map/lib/ThreadedMaterializer"):
  MaterializationError, MaterializerDebugger, ThreadedMaterializer,
  normalizeBindingTree, normalizeBindingTreeWithOrigins, tripleConstraints

ThreadedMaterializer.prototype: materialize, run (a generator, for steppers),
  liveThreads, _compileShapeExprNFA, _stepTripleConstraint, ...
```

The pipeline is two stages, joined by a JSON "binding tree":

```
source.ttl + source.shex --[shex-validate --extension]--> .val
       .val --[ShExUtil.valToExtension]--> binding tree
binding tree + target.shex --[ThreadedMaterializer]--> RDF/JS quads
```

`@shexjs/extension-map/examples/` ships eight ShExMap fixtures, including a
FHIR↔DAM blood-pressure pair. They are the best available spec of intended
behaviour and I used them as a conformance baseline (§9).

**Meaning for the pilot:** the stack installs and runs offline-reproducibly from
a lockfile. Use the API, not the CLI.

## 2. Minimal end-to-end materialization — **PASS**

`probes/p02-minimal/` — three files, ~20 lines total.

```
$ shex-validate -x source.shex -d data.ttl -m '<http://ex.example/x>@START' \
      --extension @shexjs/extension-map | shexmap-materialize -t target.shex -r 'tag:out/root'
<tag:out/root> <http://target.example/label> "Alice".
```

One gotcha: `-s START` does **not** work (`Term argument error: …/START not
found in …/S`). Use the shape-map form `-m '<node>@START'`.

**Meaning for the pilot:** the basic contract holds; `%Map:{ v:x %}` in a source
schema and the same variable in a target schema does move a value between graphs.

## 3. Nested repetition / iteration scopes — **THE GATE**

### 3a. One level of repetition — **PASS**

`probes/p03-iteration/`. One patient, two BP panels, each with systolic +
diastolic. Five input variants: canonical order, within-panel order reversed,
fully interleaved document order, blank-node panels, three panels.

```
variant A (120/80, 105/70 in order)      -> (105,70) (120,80)
variant B (dia before sys)               -> (105,70) (120,80)
variant C (all seven triples interleaved)-> (105,70) (120,80)
variant D (blank-node panels)            -> (105,70) (120,80)
variant E (three panels)                 -> (105,70) (120,80) (99,61)
```

No cross-join. No `(120,70)`. Association is preserved under every permutation
tried, and the output is grouped into per-panel target nodes.

This is a genuine improvement over the historical ShExMap materializer: alpha.33
ships a **`ThreadedMaterializer`** (see `refs/threaded-materializer.md`) that
gives every NFA thread its own binding-tree cursor, precisely to fix the
value-bag problem. The old single-cursor materializer is still in the package as
`ShExMaterializer`/`trivialMaterializer` — **do not use it.**

### 3b. Two levels of repetition — **FAIL. This is the blocker.**

`probes/p03b-two-levels/`. Patient → 2 reports → 2 panels each.
Input: report *one* = {(100,60),(101,61)}, report *two* = {(110,70),(111,71)}.

```
$ sh probes/p03b-two-levels/run.sh
<tag:out/root> t:report _:tm0 .  _:tm0 t:no "one" ; t:panel [100,60], [101,61] .
<tag:out/root> t:report _:tm3 .  _:tm3 t:no "one" ; t:panel [110,70] .
<tag:out/root> t:report _:tm5 .  _:tm5 t:no "two" .

grouping:  one: [(100,60) (101,61)]
           one: [(110,70)]          <- WRONG LABEL
           two: []                  <- EMPTY
expected:  one: [(100,60) (101,61)]
           two: [(110,70) (111,71)]
```

A report is mislabelled, a report is empty, and the panel `(111,71)` is **gone**.
Exit code 0, nothing on stderr.

Raising every search guard does not fix it (`probes/p03b-two-levels/api.js`):

```
defaults       (alts=20): one:[(100,60) (101,61)]  one:[(110,70)]  two:[]
guards raised  (alts=49): one:[(100,60) (101,61)]  one:[(110,70)]  two:[(111,71)]  two:[]
```

**Root cause — and it is structural, not a tuning problem.** The binding tree
that validation produces is *correct* and fully nested:

```json
[ {name:"Sue"},
  [ [ {reportNo:"one"}, [ {sys:100,dia:60}, {sys:101,dia:61} ] ],
    [ {reportNo:"two"}, [ {sys:110,dia:70}, {sys:111,dia:71} ] ] ] ]
```

`normalizeBindingTree()` (`src/ThreadedMaterializer.ts:80–150`) then flattens it
to a **linear tape of frames** and *distributes* any variable occurring exactly
once under an array level into every frame below it:

```
f0 = {name:Sue, reportNo:one, sys:100, dia:60}
f1 = {name:Sue, reportNo:one, sys:101, dia:61}   <- reportNo duplicated
f2 = {name:Sue, reportNo:two, sys:110, dia:70}
f3 = {name:Sue, reportNo:two, sys:111, dia:71}
```

The tape carries **no frame-boundary marker for the outer group**. The cursor
("stay on this frame if it still has an unused binding, else scan forward, never
go back") cannot know that frames 0–1 and 2–3 belong to different reports, and
`reportNo` is now available four times instead of twice. The outer repetition is
therefore unrecoverable *in principle* from the normalized input.

### 3c / 3d. Where exactly the support stops — **FAIL**

`probes/p03c-boundary/` narrows the boundary so nobody has to guess:

```
3c  two levels, NO variable on the outer group (2 reports x 2 panels)
    -> reports emitted: 1  (source had 2); all four panels hang off one report
3d  two levels, outer variable, exactly ONE inner element per group
    -> one: [(100,60) (110,70)]    two: []
```

3d is the sharpest statement: even with a single inner element per group, the
outer grouping is destroyed. **The limit is one level of repetition, full stop.**
Arbitrary *structural* nesting (non-repeating sub-shapes, e.g.
`fhir:component → fhir:valueQuantity → fhir:value`) is fine — the shipped
BP fixtures do three levels of that and pass.

Upstream corroborates this. The fixture `BPPatient-2-levels` exists, and its
*stored expected output* is itself the flattened graph: 2 reports × 2 results
become **four** DiagnosticReports and the report identity is dropped from the
target schema entirely. Upstream marks that `status: conformant`. Flattening is
the intended behaviour, not a regression.

**Meaning for the pilot:** a FHIR Bundle is naturally ≥2 levels of repetition
(Patient → many Observations → many components; Bundle → many entries → …).
A single whole-Bundle ShExMap map **will silently produce a wrong graph.**
See §10 for the resolution and §"Blocking issues".

## 4. Deterministic node identity — **PARTIAL (mostly FAIL)**

`probes/p04-identity/`.

**4a. There is no `id()`.** The Map extension registry
(`src/extensions.ts`) supports exactly three functions: `hashmap(var, {...})`,
`regex(/…(?<var>…)…/)`, and `test`. Anything else throws
`Unknown extension`. The consequence is the bad part:

```
$ shexmap-materialize -t target-id.shex ...   # target uses %Map:{ id(v:panelId) %}
<tag:out/root> <http://target.example/subjectName> "Sue".
```

The unknown function killed every thread that needed it, so **the entire
`TPanel` sub-structure vanished**, silently, exit 0. The API does record it, as
a (misleadingly named) unbound variable:

```json
"unboundVariables": [{"variable": "id(v:panelId)", "predicate": "http://target.example/iri"}]
```

**4b. A bound variable cannot name a shape-valued node.** Putting a Map
annotation on a shape-valued constraint makes the materializer emit the bound
term as a **leaf object** and *skip the sub-shape altogether*
(`_stepTripleConstraint`: the Map branch returns before the shape branch is
reached):

```
target:  <Coll> { t:panel @<TPanel>* %Map:{ v:panelId %} }
output:  <tag:out/root> t:panel <http://ex.example/p1>, <http://ex.example/p2>.
         # the systolic/diastolic sub-graph is not emitted at all
```

So you can have the IRI **or** the contents, never both in one pass. (§10 turns
this into a feature: it is exactly the join key needed to stitch passes.)

**4c. Every non-root target node is a blank node.** The only controllable IRI is
the single root, via `-r` / the `materialize(bindings, root)` argument:

```
$ shexmap-materialize -t target.shex -r 'http://out.example/Patient/abc' < out.val
<http://out.example/Patient/abc> <http://target.example/subjectName> "Sue"; ...
```

**4d. Determinism — PASS.** Two identical runs are **byte-identical, blank-node
labels included** (`_:tm0`, `_:tm1`, … a plain per-materialization counter).
Reproducible, and stronger than isomorphism.

Corollary hazard: because the counter restarts at `_:tm0` for every
materialization, concatenating two output files silently **merges unrelated
blank nodes**. I hit this for real in §10. Any multi-pass pipeline must relabel
blank nodes per pass before union (`probes/p10-workaround/merge.js`).

**Meaning for the pilot:** stable SULO IRIs cannot come from the engine. Either
(a) accept blank nodes for everything below the root and mint one root IRI per
materialization pass — which §10's decomposition gives you for free, one stable
IRI per repeated group — or (b) record an explicit decision to skolemize
host-side. Option (a) needs no postprocessor and is what I recommend.

## 5. Per-quad lineage — **PASS (API only)**

`probes/p05-lineage/`. `bin/materialize` throws this away; the API exposes it.

```
-- quads + provenance --
  tag:out/root | http://target.example/subjectName | Sue
      src={"variables":["…var#name"],"frame":0,"statics":false}  tcPredicate=…/subjectName
  tag:out/root | http://target.example/panel | tm0
      src={"structural":true}                                    tcPredicate=…/panel
  tm0 | http://target.example/systolic | 120
      src={"variables":["…var#sys"],"frame":0,"statics":false}    tcPredicate=…/systolic
  tm1 | http://target.example/diastolic | 70
      src={"variables":["…var#dia"],"frame":1,"statics":false}    tcPredicate=…/diastolic
```

`materializer.provenance` is an array **parallel to the returned quads**, each
entry `{quad, tc, predicate, src}` where `src` is one of
`{variables[], frame, statics}` (from bindings), `{constant: true}` (from a
singleton value set), or `{structural: true}` (an invented blank node link).
`tc` is the actual target-schema `TripleConstraint` object.

`materializer.frameOrigins[frame][var]` gives the JSON path back into the
original binding tree:

```json
{"…var#sys": [1, 1, "…var#sys"], "…var#name": [0, "…var#name"]}
```

**Gap:** lineage stops at the *binding tree*, not at the source triple. To reach
`<http://ex.example/p2> :sys 105`, you must join the binding-tree path against
the `.val` document (which does contain `TestedTriple` subject/predicate/object)
yourself — `valToExtension` discards it. `shex-validate --provenance` also
attaches source character ranges to the `.val`, which is the other half of the
join. This is a real integration task, not a missing capability.

**Meaning for the pilot:** target-quad → target-constraint → source-variable →
binding-tree-position is available today, in structured form. Target-quad →
source-triple needs a join we have to write.

## 6. Inverse / pivot recovery — **PASS**

`probes/p06-inverse/`. Validate the *materialized target graph* against the
*target schema* and the shared variables come straight back:

```
forward bindings (source graph @ source schema):
  [ {name:"Sue"}, [ {sys:120,dia:80}, {sys:105,dia:70} ] ]
reverse bindings (target graph @ target schema):
  [ {name:"Sue"}, [ {sys:120,dia:80}, {sys:105,dia:70} ] ]      # identical
round trip (rematerialize the SOURCE schema from the reverse bindings):
  <tag:back/root> :name "Sue"; :panel [ :sys 120; :dia 80 ], [ :sys 105; :dia 70 ].
```

Byte-for-byte the same binding tree, and the source graph reconstructs. The
upstream `BP back / simple` fixture also passes (§9).

Caveat: node **identity** does not survive the round trip — the original
`<…/p1>`, `<…/p2>` come back as blank nodes, as §4 implies.

**Meaning for the pilot:** the map is genuinely bidirectional, so a target
schema can be validated as a *specification* of what the mapping must produce,
and SULO→FHIR is reachable from the same artifacts.

## 7. Static analysis — **FAIL (absent)**

`probes/p07-static/`.

```
$ ls node_modules/.bin | grep -iE 'check|lint|analy'
  (none)
$ grep -rliE 'shexmap-?check|staticCheck|checkMap' node_modules/@shexjs/
  (none)
```

Nothing checks a source/target schema pair before data arrives. There is no
detection of unbound target variables, of variables bound in the source and
unused in the target, or of incompatible repetition scopes (§3) — the failure
mode that matters most here is exactly the one nothing looks for.

What exists is a **runtime, data-dependent** diagnostic on the API:

```json
lastReport = {
  "unboundVariables": [{"variable": "…var#diastolicTypo", "predicate": "…/diastolic"}],
  "unusedStatics": [], "alternatives": 1,
  "explorationTruncated": false, "configsPruned": 0
}
```

It is computed against the variables present *in this binding tree*, so it
cannot tell "the schema is wrong" from "this record happens to lack that field".
`shexmap-debug` (a working stepper: `s/n/o/c/b/bp/bn/t/info/l/h/q`) is the other
diagnostic, also runtime and interactive.

`shex-validate --diagnose` **crashes** in a non-TTY:

```
$ shex-validate -x target.shex --diagnose      # exit 99
TypeError: process.stdout.clearLine is not a function
    at .../@shexjs/cli/lib/ProgressLoadController.js:7:22
```

`probes/p07-static/vars.js` shows what a checker needs — the parser already
exposes every Map code per `TripleConstraint`, so a set-difference checker is
perhaps 50 lines. That is ours to write.

**Meaning for the pilot:** budget a schema-pair linter. Minimum viable check:
(1) target Map variables ⊆ source Map variables ∪ staticVars; (2) every Map code
is a bare variable or one of `hashmap`/`regex`/`test`; (3) **reject any schema
pair with two nested repeating constraints** (§3).

## 8. Failure reporting — **PARTIAL**

`probes/p08-failure/`.

**8a. Validation failures: PASS.** `shex-validate` emits a structured JSON
`Failure` on stdout and **exits 1**:

```json
{"type":"Failure","node":"http://ex.example/P","errors":[
  {"type":"TypeMismatch","triple":{"subject":"…/P","predicate":"…/panel","object":"…/p1"},
   "constraint":{"type":"TripleConstraint","predicate":"…/panel","min":0,"max":-1},
   "errors":{"type":"Failure","node":"…/p1","errors":[
     {"type":"TypeMismatch","triple":{"predicate":"…/sys","object":{"value":"not-an-integer"}},
      "errors":{"type":"NodeConstraintViolation", …, "errors":[{"type":"DatatypeMi…
```

Parses as JSON; nests to the offending triple and constraint. `--human` gives a
good repair-oriented rendering (`to conform: add 1 :sys`).

**8b. Materialization failures: FAIL on exit codes.**

```
shex-validate on nonconformant data   -> exit 1     GOOD
shexmap-materialize on a failing .val -> exit 0     BAD  (stderr "no thread reached
                                                     an accepting state"; stdout 0 bytes)
shexmap-materialize, target var never bound -> exit 0, stdout:
    <tag:out/root> <http://target.example/subjectName> "Sue".      and NOTHING on stderr
```

`bin/materialize` ends in `.catch(e => console.error(e.stack))` with no
`process.exit(1)`. **A shell pipeline cannot tell success from total failure.**
And the partial case (8c) is worse: a target variable the data never binds
silently prunes the branches that needed it, and you get a **partial graph with
a zero exit and a clean stderr**.

The API is fine. `MaterializationError` carries a parseable payload:

```
MaterializationError: no thread reached an accepting state; deepest failures:
  [{"predicate":"http://target.example/mrn","variable":"…var#noSuchVariable","frame":0}]
error.report = { "unboundVariables":[{ …, "tc": {full TripleConstraint JSON} }],
                 "unusedStatics":[], "alternatives":0,
                 "explorationTruncated":false, "configsPruned":0 }
```

**Meaning for the pilot:** never shell out to `shexmap-materialize`. Call the
API, treat a non-empty `lastReport.unboundVariables` as a hard error, and assert
`lastReport.alternatives` and `explorationTruncated` on every run.

## 9. Upstream fixture conformance — **PASS (7/8)**

`probes/p09-fixtures/` materializes each entry of
`@shexjs/extension-map/examples/manifest.yaml` from its stored bindings and
compares to the stored expected output up to blank-node isomorphism.

```
FAIL  BP / simple                        (see below)
PASS  BP back / simple
PASS  BPPatient multi-bindings / simple      <- the one-level BP panel case
PASS  BPPatient 2 levels / simple            <- matches upstream's FLATTENED expectation
PASS  symmetric / BBKing
PASS  splits / Ann-phone-mbox
PASS  splits / Ann-mbox-phone
PASS  ambiguous / Bob
fixtures: 7 pass, 1 fail
```

The single miss is a harness artefact, not an engine fault: my runner passes the
manifest's `staticVars`, so the output carries an extra
`:someConstProp "123-456"` that the stored `BP-simple-out.ttl` omits.

The engine reproduces its own fixtures. `BPPatient 2 levels` passing is the
damning one — it confirms the flattening of §3b is the *specified* behaviour.

## 10. Proposed resolution for the two-level blocker — **PASS**

`probes/p10-workaround/`. Decompose one N-level map into N one-level maps,
joined on the repeated group's own source IRI. Uses only engine features.

1. **Bind the group's IRI in the source schema** — a Map annotation on a
   shape-valued constraint:
   `<Patient> { :report @<Report>* %Map:{ v:reportIri %} }`
2. **Pass A — skeleton.** Target `<Coll> { t:report IRI* %Map:{ v:reportIri %} }`.
   By §4b this emits the *source IRIs as leaf objects*, which is precisely the
   join key.
3. **Pass B — per group.** For each of those IRIs, validate `<iri>@<Report>` and
   materialize the inner target **rooted at that same IRI** (`-r <iri>`).
   Each pass now contains one level of repetition, the regime that works.
4. **Union**, relabelling blank nodes per pass (mandatory — §4d).

```
$ sh probes/p10-workaround/run.sh
pass A: <http://out.example/Patient/P> t:subjectName "Sue";
                                       t:report <…/r1>, <…/r2>.
pass B: <…/r1> t:no "one"; t:panel [100,60], [101,61].
        <…/r2> t:no "two"; t:panel [110,70], [111,71].
union:  one: [(100,60) (101,61)]
        two: [(110,70) (111,71)]        <- CORRECT
```

The host chooses root nodes and unions graphs. It never edits a triple the
engine emitted. Blank-node relabelling is semantically a no-op (blank node
labels are document-scoped) and is forced by the counter restart.

Bonus: every repeated group now has a **stable target IRI** derived from its
source IRI, which is most of what §4 said was missing.

## 11. Scale — **FAIL by default, fixable via the API**

`probes/p11-scale/`. The most dangerous finding in this report.

```
$ sh probes/p11-scale/run.sh
### 60 panels in the source graph, via the CLI (default options)
  exit=0  stderr:
  CLI panels emitted: 19   (source had 60)
### 200 panels in the source graph, via the CLI (default options)
  exit=0  stderr:
  CLI panels emitted: 19   (source had 200)
```

Sixty panels in, nineteen out. Exit 0. Empty stderr. Threshold and root cause:

```
  n=  15 defaults  panels= 15/15   alts=16
  n=  20 defaults  panels= 19/20   alts=20     <- cap reached
  n= 100 defaults  panels= 19/100  alts=20
  maxRepeat 1000                  panels=19/200   (no effect)
  exploreSteps 1e7                panels=19/200   (no effect)
  maxAccepts > n                  panels=200/200  <- THE FIX
```

**Root cause:** `this.maxAccepts = options.maxAccepts || 20`
(`ThreadedMaterializer.ts:201`). The scheduler defers any constraint that has to
advance the frame cursor, so accepting threads are discovered in increasing
repetition count (1, 2, 3, …). At 20 recorded accepts the search stops
(`accepts.length >= this.maxAccepts` → `break search`) and returns the best found
so far — 19 repetitions. `lastReport.explorationTruncated` stays **false**,
because this is not the `exploreSteps` truncation it reports on. `maxRepeat`
(50) and `exploreSteps` are red herrings. **`bin/materialize` exposes no way to
set `maxAccepts`** — its only options are `-h -j -r -t`.

With `maxAccepts` raised, output is complete and performance is quadratic but
workable:

```
  n= 100  100/100    25ms
  n= 500  500/500   473ms
  n=1000 1000/1000 2073ms
  n=2000 2000/2000 12436ms
```

Note also `alternatives` grows as n+1 — the engine enumerates one accepting
materialization per repetition count and then picks. Set `maxAccepts` generously
above the largest expected repetition count, and assert that the chosen accept
consumed every binding.

**Meaning for the pilot:** any real FHIR Bundle exceeds 19 repeated elements
immediately. Using the shipped CLI on real data would have produced plausible,
quietly truncated output. This alone disqualifies `shexmap-materialize`.

---

# Blocking issues

### B1 — Two or more levels of repetition are silently mis-mapped · **BLOCKER**

Reproducer: `sh probes/p03b-two-levels/run.sh` (plus `api.js` to show the guards
don't help; `probes/p03c-boundary/run.sh` for the exact boundary).
Symptom: outer-group labels mis-associated, an entire inner element dropped,
exit 0, no diagnostic. Cause: `normalizeBindingTree` flattens the (correct)
nested binding tree to a frame tape with no outer-group boundary and duplicates
outer variables into every inner frame. Not tunable; upstream's own fixture
expects the flattening.

**Proposed resolution — use the decomposition of §10, as a recorded architectural
decision.** One map per level of repetition, each rooted at the repeated group's
own source IRI, unioned with per-pass blank-node relabelling. Verified working
(`probes/p10-workaround/`). It uses only engine features; the host picks roots
and unions, and never rewrites a triple.
Consequence to accept explicitly: **map authors may not write a schema pair with
two nested repeating constraints.** The linter of B4 must enforce this, and the
pipeline gains a driver loop. Do not paper this over inside a materializer wrapper.

Fallback if the decomposition proves too costly for real FHIR nesting depth:
patch `normalizeBindingTreeWithOrigins` to emit group-boundary markers and teach
the cursor to respect them. That is a real upstream change (contributable), not
a config flag — do not plan around it for the pilot.

### B2 — The CLI silently truncates every repetition to 19 items · **BLOCKER**

Reproducer: `sh probes/p11-scale/run.sh` — 60 panels in, 19 out, exit 0.
Cause: `maxAccepts` defaults to 20; `bin/materialize` cannot set it.

**Proposed resolution: drop `shexmap-materialize` from the pipeline entirely and
drive `ThreadedMaterializer` from the API** with `maxAccepts` (and `maxRepeat`,
`maxSteps`, `exploreSteps`) raised well above the data's cardinality. Verified
(`probes/p11-scale/scale.js`). Add a regression test that materializes 100
repeated elements and asserts 100 out. `shex-validate` stays as-is (it is fine).

### B3 — Materialization failures are invisible to a shell pipeline · **BLOCKER (if CLI used)**

Reproducer: `sh probes/p08-failure/exitcodes.sh`.
`shexmap-materialize` exits 0 on a fatal error (empty stdout) *and* on a
partially-materialized graph (no stderr at all).

**Proposed resolution:** subsumed by B2 — use the API, and make the pipeline
fail on any of: a thrown `MaterializationError`; non-empty
`lastReport.unboundVariables`; `lastReport.explorationTruncated === true`; or a
chosen accept that did not consume every binding. All four are available on the
materializer object.

### B4 — No static checker · **MAJOR (not blocking)**

Reproducer: `sh probes/p07-static/run.sh`. A typo'd target variable is caught
only at runtime and only via the API; `--diagnose` crashes in a non-TTY
(`process.stdout.clearLine is not a function`, exit 99).

**Proposed resolution: write one (~50 lines, host-side, explicitly ours).**
`probes/p07-static/vars.js` shows the parser already yields every Map code per
`TripleConstraint`. Checks: target vars ⊆ source vars ∪ staticVars; every Map
code is a bare variable or `hashmap`/`regex`/`test`; **no two nested repeating
constraints** (enforces B1). Run it in CI over every schema pair.

### B5 — No minted target IRIs; blank-node labels collide across passes · **MAJOR**

Reproducer: `sh probes/p04-identity/run.sh`; the collision bit is visible in the
first (broken) iteration of the §10 union.
There is no `id()`; an unknown Map function silently deletes the whole shape
that used it. Only the root node's IRI is controllable.

**Proposed resolution:** take the stable IRIs that §10's decomposition already
yields (one per repeated group, derived from the source IRI) and accept blank
nodes below them. If more are needed, skolemize host-side as a **recorded
decision**, not a hidden step. Independently: **always relabel blank nodes per
materialization before union** (`probes/p10-workaround/merge.js`) — the counter
restarts at `_:tm0` every time.

# What Agent 4 recommends

1. **GO** on ShEx.js `1.0.0-alpha.33` from npm, driven by the
   `ThreadedMaterializer` **API** with raised guards. The npm release is sound;
   no git build needed.
2. **Ban `shexmap-materialize`** from the pipeline (B2, B3). Keep
   `shex-validate --extension` for the binding-extraction half.
3. **Adopt the one-level-per-pass decomposition** (§10) as an explicit
   architectural decision and tell every other agent: a schema pair may contain
   at most one repeating constraint on any path.
4. **Build two small host-side tools**, both named and owned, neither hidden: a
   schema-pair linter (B4) and a materialization driver that enforces the
   fail-fast assertions of B3 and does blank-node-safe union (B5).
5. **Wire `provenance` / `frameOrigins` into the pipeline from day one** (§5) —
   it is free now and expensive to retrofit.

# Files

```
FINDINGS.md          this document
package.json         pinned install
package-lock.json    245 packages, resolved URLs + integrity hashes
run.sh               re-runs everything from clean (--keep to reuse the container)
verdicts.sh          runs inside the container; one PASS/FAIL line per probe
probes/              every schema, graph and script used, each runnable
  p01-surface/         CLI binaries + programmatic API surface
  p02-minimal/         smallest working end-to-end map
  p03-iteration/       ONE level of repetition, 5 input permutations   PASS
  p03b-two-levels/     TWO levels of repetition                        FAIL (B1)
  p03c-boundary/       where nesting support stops (3c, 3d)            FAIL
  p04-identity/        id(), var-as-node, determinism, root IRI
  p05-lineage/         per-quad provenance + lastReport (API)
  p06-inverse/         target -> source pivot and round trip           PASS
  p07-static/          absence of a static checker; what one needs
  p08-failure/         failure shapes and exit codes
  p09-fixtures/        conformance vs upstream's own fixtures
  p10-workaround/      the proposed resolution for B1                  PASS
  p11-scale/           the 19-item truncation, its cause and its fix
  pairs.js bindings.js shared helpers
refs/                copied out of the installed package for reading:
  examples/            upstream ShExMap fixtures (incl. the FHIR/DAM BP pair)
  bin/                 materialize + shexmap-debug sources
  threaded-materializer.md   the design doc for the alpha.33 materializer
  extension-map-README.md
```
