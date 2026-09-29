# DR-605 — R5 unset rejects; validation moves onto real map output

**Status:** Decided (Agent 6), in response to an independent review
**Date:** 2026-09-29
**Gate:** 2, 3, 4
**Supersedes in part:** [DR-603](DR-603-shacl-for-target-validation.md)
**Related:** review items R5 (open), R6 (open), R2 (open)

Four findings, three fixed here and one blocked. Each was reproducible; none was disputed.

---

## 1. R5 was quietly decided as option B (MAJOR)

### What was wrong

```python
R5_RESOLVED = False
CONCEPT_NOTE_LITERAL = Strictness()      # both flags off
R5_OPTION_B = CONCEPT_NOTE_LITERAL       # the same object
```

`R5_RESOLVED = False` was **decorative**. `validate_graph` defaulted to the permissive setting,
the CLI defaulted to it, the benchmark ran under it, and a test named
`test_option_b_is_the_default_and_the_graph_conforms` pinned it. So option B was in force
everywhere while the flag said the question was open. The review demonstrated it: deleting
every `isFeatureOf` from a real expected graph still conformed.

DR-603 claimed the switch meant "a reviewer answer flips behaviour without re-authoring maps".
True — but it left out that *not* answering also selected a behaviour.

### The fix: the R2 model

Agent 5's quality-identity block is the template, and it is followed literally:

| | R2 (Agent 5) | R5 (here) |
| --- | --- | --- |
| record | `policies/identity-policy.v1.json` | `src/fhir_sulo/validation/r5-strictness-policy.json` |
| unset value | `"mode": null` | `"mode": null` |
| unset behaviour | `"reject"` | `"reject"` |
| both options implemented | yes | yes |
| proof | a request is refused | `resolve()` raises `R5PolicyUnset` |

Concretely:

- `resolve()` and `resolve("from-policy")` both raise `R5PolicyUnset` while the recorded mode is
  `null`. They are deliberately the same call: there is no spelling that looks deliberate but
  still picks an answer.
- `validate_graph(data, strictness)` and `load_shapes_graph(strictness)` take strictness as a
  **required positional argument**. A test inspects the signature and fails if a default returns.
- `--strictness` is **required** on `fhir_sulo.validation.cli shapes` and on the benchmark, so
  every gate artefact names the strictness it was produced under.
- R5 option C (a per-axiom split) requires a stated `rationale`. An unlabelled half-strict
  setting cannot be told apart from an oversight.

Choosing `concept-note-literal` is still allowed and still passes. The change is that a run must
*say so*, and saying so is recorded in the validation report digest.

**R5 is not answered by this decision record.** `mode` is still `null`.

### Why R5 is not in the graph key

R5 decides how a graph is *checked*, not what is emitted, so it is deliberately not one of
`graph_key.CONTENT_FIELDS` — answering it must not re-key every graph. It does change
`validation_report_digest`, which is correct.

### Where the policy file lives

`src/fhir_sulo/validation/`, not `policies/`. `PolicyBundle.policy_version` composes exactly
three Agent 5 tables into one string; adding a fourth would change that string and is an
interface change Agent 6 should not make unilaterally. **Proposed for relocation into
`policies/` at integration**, with the caveat that it must not enter `policy_version` unless the
team decides validation strictness belongs in the graph key, which it does not.

---

## 2. Validation, reasoning and competency checks ran on hand-written graphs (MAJOR)

### What was wrong

Every Gate 2/3 check ran on `tests/integration/graphs/*.ttl`, which is not what the maps emit:

| | hand-written | real map output |
| --- | --- | --- |
| person IRI | `ex:person-p123` | `person-<32 hex>` |
| person type | `sulo:SpatialObject` | `sulo:Object` |
| quality type | `sulo:Feature` | `sulo:Quality` |
| time datatype | `xsd:dateTimeStamp` | `xsd:dateTime` |

The properties hold on both, so this was not a correctness bug. But a Gate 3 condition backed by
a graph no pipeline produces establishes nothing, and would not notice the map drifting.

### The fix

`tests/integration/mapoutput.py` reads `fixtures/expected/*/*/target.nt` — the graphs Agent 3's
maps produce, drift-checked by `fixtures/expected/build.py`. The suites now assert over them:

- **SHACL**: all nine emitted graphs conform, individually and as one merged batch (the orphan
  and cross-patient constraints are graph-wide, so per-fixture is not sufficient).
- **Reasoning**: consistency for all nine; for both encounter fixtures, both role holders are
  inferred as participants, neither was asserted, and the two holders are distinct. Role and
  holder IRIs are **discovered from the graph**, never hard-coded, because real IRIs are content
  hashes that move when the identity policy moves.
- **Competency queries**: CQ1 on `egfr-baseline`, CQ2 on `bp-two-panels`,
  `bp-reordered-serialisation`, `bp-duplicate-values` and `bp-component-omitted`, CQ3 on
  `enc-baseline` reasoned. Negative queries on every emitted graph and on the merged batch.
- **Correction (Gate 4)**: `support.QUADS_V1` is now the real 21-triple `egfr-baseline` graph,
  and the `entered-in-error` test takes its rejection reason from the real
  `egfr-entered-in-error` outcome.

Hand-written graphs are kept **only** where no correct map emits them and they are the failure
the test must detect: `negatives.ttl` and `bp-cross-join.ttl`.

### Three things this immediately caught

1. **The R6 typing disagreement** — see §3. Found only because the suites moved.
2. **`xsd:dateTime` timezone canonicalisation.** rdflib renders the maps'
   `"…T14:00:00Z"^^xsd:dateTime` as `…T14:00:00+00:00`. Same instant, different spelling. The
   old `xsd:dateTimeStamp` graphs had no Python mapping so the lexical form survived and this
   never appeared. Normalised in one helper, `mapoutput.iso_z`.
3. **`bp-other-patient` holds two people, not one.** A test written against the hand-written
   graph assumed one. The right assertion is not "one row" but "every row returned for a person
   is about that person, and the two people's answers are disjoint" — which is the actual
   cross-patient property.

### Still outstanding: a genuine version-2 fixture

The fixture set has **no pair of fixtures that are two versions of the same resource**.
`egfr-entered-in-error` is a different resource id (`egfr-456-eie`), not version 2 of
`egfr-456`. So the v1→v2 correction test uses the real version-1 graph with the reported value
corrected — 20 of 21 triples are map output and the one synthetic literal is called out in
`support.py`.

**Requested from Agent 2: an `egfr-corrected` fixture** — the same resource at
`meta.versionId = 2` with a different value. Gate 4's correction row is the only place in the
acceptance matrix that needs one, and nothing but a fixture can supply it.

---

## 3. R6: the person class choice has a measured consequence

DR-603 said the reasoner catches a person wrongly typed into a `Feature` branch, "so R6 has a
safety net while it is open". **That is false for the typing the maps actually use.**

SULO 0.2.12 has `Feature ⊑ Object` and `Feature owl:disjointWith SpatialObject`. Measured with
HermiT on the pinned image:

| person typed as | alone | + `sulo:Quality` | + `sulo:Role` |
| --- | --- | --- | --- |
| `sulo:SpatialObject` | consistent | **INCONSISTENT** | **INCONSISTENT** |
| `sulo:Object` (what the maps emit) | consistent | consistent | consistent |

Because `Quality ⊑ Feature ⊑ Object`, there is no clash. **Under the current typing there is no
OWL guard against a patient being typed as a Role.**

This is not a crisis: the SHACL disjointness shapes reject such a node, so it never reaches the
store. But the guard is in SHACL, not in OWL, and the acceptance matrix row that says "an OWL
reasoner checks consistency" leans on the one that is absent.

**Input to R6, not an answer to it.** Choosing `sulo:SpatialObject` buys a consistency guard
that bare `sulo:Object` does not. Recorded as tests
(`R6EvidenceThePersonClassChoiceHasConsequences`) rather than prose, so it stays true.

A second test pins the map's current choice, so Agent 3's emitted typing and Agent 6's tests
cannot disagree silently again — which is how this was missed the first time.

---

## 4. `validation_report_digest` carried no information (MINOR, fixed)

The digest hashed only the findings. A conforming report has none, so **all nine expected graphs
and the 10,000-resource benchmark produced the identical digest** `5d2a2384…`. A validation
digest that cannot tell you what was validated is not evidence.

`ShapeReport` now carries `data_digest` (canonical sorted N-Triples of the validated graph),
`triples_validated` and `focus_nodes`, and all three go into the digest.

The test asserts the right invariant, which is **not** "all digests differ":
`bp-reordered-serialisation` is supposed to emit a graph byte-identical to `bp-two-panels`, so
those two *must* share a digest. What must hold is that two fixtures share a digest **iff** they
emitted the same triples.

---

## 5. Blocked: the benchmark still excludes the transformation (MAJOR)

`benchmarks/generator.py` emits SULO target triples directly. The benchmark measures keying,
lineage, the store, provenance, SHACL and OWL reasoning — **not** rendering, the maps, or the
engine. `benchmarks/README.md` and DR-604 both said so, but the number is still not what plan
Gate 4 asks for.

**This is blocked on Agent 4's B1** (composing ingest → driver → store). The driver is currently
imported only by its own tests and by `tools/engine/`; there is no composed pipeline to measure.

### The plan, ready to execute when B1 lands

1. Add a `render` stage (Agent 2's JSON → FHIR RDF) and a `materialize` stage (Agent 4's driver
   over Agent 3's `maps/r4/`), between `generate` and `keying+lineage+store`.
2. Feed the store from driver output rather than from `generator.py`. The generator stays, behind
   `--synthetic-targets`, for measuring the host layers in isolation and for bisecting a
   regression to one stage.
3. Extend the corpus generator to emit **FHIR JSON**, not target triples. It already models the
   family mix and the ineligible cases; only the output format changes.
4. Re-measure and report honestly. **Treat the target as genuinely at risk again**: the 0.30 s
   engine figure came from a toy two-component schema, not the ten-pass BP map. Part A2 of the
   engine benchmark already shows that binding extraction through the shipped CLI alone would
   cost 17 minutes for 10,000 resources — under budget only because Agent 4's driver runs
   in-process.
5. If the targets are missed, report the numbers and a diagnosis. **Not a softened target.**

Agent 1 is separately tightening `gate-check.check_benchmark` to verify stages, resource count
and memory rather than the single `passed: true` boolean it reads today — which is the right
fix, and would have caught this.

---

## 6. Noted, not changed: R2 mode selection in fixture generation

Every gate artefact is generated under R2 `per-observation`. The **recording** is already
correct: `fixtures/expected/build.py` writes `run_parameters.quality_identity_mode` into every
`outcome.json`, with a note saying the mode was set explicitly because the shipped default
rejects. A test here now asserts that field is present and valid on every emitted fixture.

What remains implicit is two **function defaults** in Agent 3's case runners:

```python
# tests/contracts/maps/egfr_case.py:41  and  bp_case.py:61
def run(fixture_id: str, *, quality_mode: str = "per-observation", ...)
```

A caller that omits `quality_mode` silently gets option B's sibling. Removing the defaults so the
mode must be passed would close it.

**Not changed here**, because `fixtures/` is explicitly outside Agent 6's ownership and
`tests/contracts/maps/` is Agent 3's. Raised for Agent 3 with the exact two lines.
