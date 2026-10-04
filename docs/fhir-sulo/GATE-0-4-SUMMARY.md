# Gates 0–4: what was built, what is proven, what is not

A reading order for reviewers. The branch is large because it implements six parallel
workstreams from the implementation plan; this page says what to read and in what order,
and is honest about what does not hold.

**Status in one line:** all five gates pass, and **all 12 review items are answered**. Gate 0's
sign-off condition (R7, the record/fact distinction) was signed on 2026-10-03, which released
the ordering hold on Gates 1–4.

Answered is **not** signed off: every terminology and vocabulary binding is still
`pilot-provisional` and nothing is `approved`, which is why
[`REVIEW-REQUEST.md`](REVIEW-REQUEST.md) stays `Status: OPEN`.

```
$ FHIR_SULO_REQUIRE_ENGINE=1 FHIR_SULO_ENGINE_TESTS=1 python3 tools/gate-check.py --all
Gate 0 PASSED  (9 pass, 0 fail, 0 manual)
Gate 1 PASSED  (6 pass, 0 fail, 0 manual)
Gate 2 PASSED  (5 pass, 0 fail, 0 manual)
Gate 3 PASSED  (4 pass, 0 fail, 0 manual)
Gate 4 PASSED  (5 pass, 0 fail, 0 manual)

Gates passing: 5 of 5
```

Gate 5 is **not** begun; it is out of scope by instruction. Nothing here is validated for
clinical use.

## Read in this order

1. **[`REVIEW-REQUEST.md`](REVIEW-REQUEST.md)** — 12 clinical and ontology questions. **Nothing
   is approved.** Start here: R1 and R2 block the most, and should be answered together because
   both re-key every quality IRI.
2. **[`CONTRACT-DEVIATIONS.md`](CONTRACT-DEVIATIONS.md)** — six places the toolchain cannot meet
   the acceptance contract literally, with the substitute and its justification. CD-1 (`id()`
   does not exist) and CD-6 (the OWL consistency row overstates what the reasoner catches) are
   the two that change what a row promises.
3. **[`decisions/DR-007-integration-record.md`](decisions/DR-007-integration-record.md)** — what
   the merge itself found, including three claims this repository made that were wrong, and the
   Gate 4 measurement.
4. **[`decisions/DR-302-one-repetition-per-path.md`](decisions/DR-302-one-repetition-per-path.md)**
   — the architectural constraint everything else is shaped by.
5. `maps/r4/` and `fixtures/expected/` — the actual mapping contract.

## What is genuinely proven

- **The blood-pressure requirement.** The multiset `{(bp-1,120,80),(bp-2,105,70)}` is asserted
  **on the emitted target graph**, recovered via the graph's own `prov:wasDerivedFrom`, with
  each slot decided by the class of the quality its quantity refers to. Injecting a
  cross-wire into the target schema — and rehashing so the tamper check cannot mask it — fails
  ten tests.
- **No host-side triple construction.** Every emitted quad names a `TripleConstraint` its own
  target schema declares; the host supplies root IRIs and static variables and unions passes.
  A test asserts this over the real maps and fails on a forged quad.
- **The PRO entailment**, with a working negative control: HermiT materializes
  `encounter hasParticipant person` from the role chain, ELK demonstrably does not.
- **Determinism**, across separate processes and separate engine invocations. This carries the
  Gate 4 idempotence story, because the engine has no `id()` and node identity comes from the
  identity service.
- **Source fidelity.** The renderer is validated graph-isomorphically against HL7's own
  published Turtle for the three examples the concept note cites, and 19 targeted mutations of
  the canonical RDF must each be detected.
- **Correction**, on one real resource lineage (`egfr-456` at v1, v2, v3) through the real
  pipeline.

- **Gate 4 scale**, on the real pipeline: 10,000 resources in **3.8 min** against a 15 min
  target and **4.97 GB** against 6 GB. The first honest measurement was 78.1 min; the profile
  showed 72% of the per-resource cost was Docker container start-up, the engine was made
  resident, and the total fell 20.5× with output unchanged — 9,510 mapped, 490 not, 261,236
  triples, identical to the slow run and asserted quad-for-quad against a one-shot engine.
  The target was never moved and the corpus never shrunk.

## After the gates: reviewer decisions and cross-system identity

The gates were met before the reviewer answered. Answering them changed the system rather than
confirming it, and the four most consequential changes are worth reading before the diff.

**R8a — OntoClean.** `entity_kind` is a key input, so `"practitioner"` was acting as an
*identity criterion*: an anti-rigid property grounding a person's identity. Both Patient and
Practitioner references now mint `person` entities and the role moved to `ex:PractitionerRole`.
An undeclared entity kind is rejected rather than slugified into an IRI segment
([DR-010](decisions/DR-010-ontoclean-practitioner-is-a-role.md)).

**R9a — a conformance claim nothing checked.** `validated_profiles` meant "declared and
recognised": a resource could claim `vitalsigns` with nothing verifying it, and a test asserted
exactly that using an *eGFR* resource. It now means **checked and passed**
([DR-012](decisions/DR-012-r9-vitalsigns-conformance-and-the-panel-code.md)).

**The source scope was a module constant.** The identity policy promises that two sources
holding `Patient/p123` get different IRIs. It delivers that; the *pipeline* passed one
hardcoded scope for every resource, so two hospitals' `Patient/123` became **one person**. Two
humans fused, nothing reporting it. No test caught it and more of the same would not have —
every fixture came from one source, and the unfixed code passed 959 tests
([DR-014](decisions/DR-014-the-source-scope-was-a-module-constant.md)).

**Cross-system reunification, conditional on a person-level identifier.** A BSN lives on
`Patient.identifier`, which this pipeline never ingests, so a digested **index** supplies it as
an input ([DR-015](decisions/DR-015-person-identifier-index.md)). The index is part of the
graph key, because without it one key named two different graphs
([DR-016](decisions/DR-016-the-index-belongs-in-the-graph-key.md)) — and that fix also removed
the need for a bespoke migrator, since the *subject* key is unchanged and supersession already
handles the rest. Identifier systems are canonicalised across spellings, because BSN arrives
both as a `fhir.nl` URI and as a `urn:oid:`
([DR-017](decisions/DR-017-one-identifier-system-has-several-spellings.md)).

Demonstrated end to end in `fixtures/multi-source/` — the first corpus here with more than one
source — where two hospitals' eGFR results attach to one person, a third patient does not
merge, and a control shows that without the index the same two inputs give two people.

## What is not proven, stated plainly
- **Iteration scopes are never exercised by a production map.** All three shipped pairs are
  repetition depth 0 — BP discriminates components by LOINC code rather than position, which is
  a stronger guarantee but a different one from the plan's repetition risk row. See DR-302.
- **`Encounter.participant` is capped at cardinality 1**, so "who participated in this
  encounter" answers only for single-practitioner encounters. A second participant fails loudly.
- **No OWL guard against a person typed as a Role** under the current `sulo:Object` typing —
  SHACL catches it. CD-6, and input to R6.
- **`Observation.method` is held at reject** rather than resolved: the profile lists it
  source-only, concept note §2 says it must not be dropped while claiming an unqualified
  numeric result. Review item N4.

## Running it

```bash
make venv                 # pinned dev + runtime dependencies
make contracts            # full suite (pytest, authoritative)
make contracts-stdlib     # same invariants, standard library only, no install

make engine-live          # engine + tools, live engine REQUIRED (Docker)
make lint-schemas         # static analysis of every committed ShExMap pair
./benchmarks/run.sh       # 10,000 resources under Gate 4's limits

# end to end, FHIR JSON to store
python -m fhir_sulo.pipeline.cli batch --family bp --quality-mode per-observation \
  --out batch.jsonl --load store/ fixtures/r4/bp/bp-two-panels/bp-{1,2}.json
python -m fhir_sulo.store.cli inspect --state store/state.json
```

`tools/gate-check.py` encodes the plan's pass conditions as executable checks. A condition with
no mechanical check reports `MANUAL` and blocks; a check that raises reports `FAIL`; gates
advance in order, so a later gate reports `HELD`, never `PASSED`, while an earlier one is
blocked. `--fail-on mechanical` is what CI uses, so an unanswered review does not hold the build
red forever; the default asks the stricter question.
