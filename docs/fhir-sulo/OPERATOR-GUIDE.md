# Operator guide

**Owner:** Agent 6. **Gate:** 4. **Updated:** 2026-09-29.

> The pilot is complete when … an operator can run and inspect a batch without editing code.
> — plan §8

This guide covers the stages Agent 6 owns: **loading a batch into the versioned graph store,
applying corrections, and checking the result** (shapes, OWL reasoning, competency queries).
Every command here is exercised by `tests/integration/test_operator_cli.py`, so the guide cannot
drift from the software without a test failing.

The composed pipeline now exists, so §3 starts from **real FHIR JSON** rather than from
synthetic output. `python -m fhir_sulo.pipeline.cli` (Agent 4) runs ingest, RDF rendering, the
reviewed maps and the pinned engine, and writes the batch manifest this guide's store commands
read.

---

## 1. Set up

Requirements: `python3` (3.9+), `docker`. **No Node, npm or `java` needed on the host** — the
OWL reasoner runs in a pinned container.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-runtime.txt
```

`fhir_sulo.contracts`, `fhir_sulo.store` and `fhir_sulo.provenance` are stdlib-only and run on a
bare interpreter. Only shape validation, reasoning and the benchmark need the venv.

Run everything from the repository root with `PYTHONPATH=src`.

## 2. Check the reasoner first

**Do this before anything else, on every new machine.**

```sh
PYTHONPATH=src .venv/bin/python -m fhir_sulo.validation.cli reasoner-check
```

```
reasoner:                 HermiT
entailment materialized:  True
refutation detected:      True
verdict:                  USABLE
```

The pilot depends on a SULO property chain containing an inverse property, which needs an OWL 2
DL reasoner. **A weaker reasoner does not報 an error — it returns fewer entailments and exits
0.** This command is the only thing that tells you the difference. If it prints `NOT USABLE`,
stop: every downstream result will be quietly wrong. See DR-602.

First run pulls the pinned image and takes a minute; afterwards it takes a few seconds.

## 3. The batch manifest

A batch is a **JSON Lines** file, one transform per line:

```json
{"inputs": {"source_canonical_url": "https://fhir.example/Observation/egfr-1",
            "source_version_id": "1",
            "source_json_digest": "sha256:…",
            "map_id": "egfr-r4",
            "map_semantic_version": "0.1.0",
            "pairing_hash": "sha256:…",
            "sulo_version": "0.2.12",
            "domain_ontology_version": "unresolved:R1",
            "terminology_snapshot": "tx-2026-09-29",
            "policy_version": "unresolved:R2",
            "engine_build": "shex@1.0.0-alpha.33",
            "contract_version": "0.1.0"},
 "status": "mapped",
 "source_status": "final",
 "quads": ["<s> <p> <o> ."],
 "pivot_variables": ["egfr:value"],
 "engine_provenance": [{"quad": "<s> <p> <o> .", "tc": "…", "src": "egfr:value", "frameIndex": 0}],
 "frame_origins": [{"frameIndex": 0, "scope": "result", "keyValues": ["egfr-1"]}]}
```

- `status` is `mapped`, `source-only` or `rejected`.
- A non-`mapped` line carries `reason` instead of `quads`, **and it is still written to the
  manifest.** That is not an omission and the line must not be filtered out: loading it
  **retracts** whatever graph the store currently holds for that resource. This is how an
  `entered-in-error` correction actually takes effect — the pipeline never reaches the engine
  for an ineligible resource (concept note §2), so the retraction is the only signal the store
  gets. Dropping non-mapped lines from a batch would silently leave stale clinical assertions
  in the current graph.
- `engine_provenance` must be **parallel to `quads`**: one entry per quad, same order. This is
  the shape the pinned engine's `materializer.provenance[]` has (DR-301 probe 5). A mismatch is
  rejected with the offending line number rather than producing a graph with untraceable
  triples.
- Every one of the thirteen `inputs` fields is required and must be non-empty. An undecided policy
  is recorded as an explicit token such as `"unresolved:R1"`, never as `""` — see DR-601.

### Producing one from real FHIR JSON

This is the normal path. One command runs ingest, RDF rendering, the maps and the engine, and
writes the manifest:

```sh
PYTHONPATH=src python3 -m fhir_sulo.pipeline.cli batch \
    --family bp --quality-mode per-observation \
    --out batch.jsonl \
    fixtures/r4/bp/bp-two-panels/bp-1.json fixtures/r4/bp/bp-two-panels/bp-2.json
```

`--quality-mode` is **required** for `bp` and `egfr`: review item **R2** is open and the shipped
policy default rejects every quality-identity request, so a run must name the answer it used.
`--family` is one of `egfr`, `bp`, `encounter`.

`--load DIR` goes straight on to load it, writing `state.json`, `provenance.nq` and `graph.nt`
into that directory — equivalent to the `batch` command followed by §4's `store.cli load`:

```sh
PYTHONPATH=src python3 -m fhir_sulo.pipeline.cli batch \
    --family bp --quality-mode per-observation \
    --out batch.jsonl --load store/ \
    fixtures/r4/bp/bp-two-panels/bp-*.json
```

A purely synthetic manifest, for exercising the store commands without the engine:

```sh
PYTHONPATH=src:benchmarks python3 benchmarks/run_benchmark.py \
    -n 200 --strictness concept-note-literal --synthetic-targets --emit-batch batch.jsonl
```

## 4. Load a batch

```sh
PYTHONPATH=src python3 -m fhir_sulo.store.cli load \
    --batch batch.jsonl \
    --state store-state.json \
    --graph current.nt \
    --provenance prov.nq
```

```
created        183
held            17

archived_graphs    0
archived_triples   0
current_graphs     183
current_triples    4106
runs               200
source_versions    200
state_digest       44a5c4c7e1472b4d…
```

| Action | Meaning |
| --- | --- |
| `created` | first graph for this resource |
| `replaced` | a later source version superseded the previous graph |
| `unchanged` | identical reprocessing; **the current graph was not touched** |
| `invalidated` | a `source-only`/`rejected` result retracted a current graph |
| `held` | not eligible, and there was nothing current to retract |

Outputs:

- `store-state.json` — the whole store: current graphs, archive, source registry, run ledger.
  Pass the same path next time to continue; it round-trips exactly.
- `current.nt` — the current semantic graph, N-Triples.
- `prov.nq` — PROV-O, N-Quads. Provenance lives in `urn:fhir-sulo:prov:*` named graphs and never
  enters the semantic graph.

Add `--activity-time 2026-09-29T12:00:00Z` for a reproducible run, and `--keep-going` to process
the whole batch and report failing lines at the end instead of stopping at the first.

### Re-running an unchanged batch

```sh
PYTHONPATH=src python3 -m fhir_sulo.store.cli load --batch batch.jsonl --state store-state.json
```
```
unchanged      183
held            17
```

The current triples, the per-graph objects and `state_digest` are all identical. The runs are
still appended to the ledger — a confirming run is a fact worth recording — but the graph keeps
its *original* generating run, so "who produced this triple" does not change every time someone
re-runs the batch.

## 5. Apply a correction

Nothing special to do: **load the new version.**

```sh
PYTHONPATH=src python3 -m fhir_sulo.store.cli load --batch batch-v2.jsonl --state store-state.json
```
```
replaced         1
```

Version 1's derived assertions leave the current graph and move to the archive; its graph, its
lineage and its run record stay retrievable, and its run record is marked `superseded_by`.

For `entered-in-error`, emit a `source-only` line with a `reason`. The clinical assertions are
retracted and **the source record is retained** (concept note §2) — the registry is append-only
and nothing removes from it.

Inspect the history:

```sh
PYTHONPATH=src python3 -m fhir_sulo.store.cli inspect --state store-state.json --subject urn:fhir-sulo:s:…
```
```
history of urn:fhir-sulo:s:9c1f…
  superseded v1    urn:fhir-sulo:g:9c1f…:a3b8…
             run   run-4f2a…
             quads 19
             why   superseded by source version 2
  current    v2    urn:fhir-sulo:g:9c1f…:77d1…
             run   run-91be…
             quads 19
```

Find a subject key with `inspect --state store-state.json` (no arguments), or compute it from
the inputs with `key`.

## 6. Inspect one graph, one run, one key

```sh
# a graph, with its triples
python3 -m fhir_sulo.store.cli inspect --state store-state.json --graph-key urn:fhir-sulo:g:… --quads

# a run record and its PROV-O
python3 -m fhir_sulo.store.cli run run-4f2a… --state store-state.json

# what key would these inputs produce? (answerable BEFORE running the transform)
python3 -m fhir_sulo.store.cli key --inputs inputs.json
```

## 7. Verify the audit trail

```sh
PYTHONPATH=src python3 -m fhir_sulo.store.cli verify --state store-state.json
```
```
checked 200 run records
every graph key recomputes from its run record
state digest: 44a5c4c7e1472b4d…
```

Every graph key is a function of its own run record's fields, so this recomputes all of them and
reports any that disagree. A key that could not be recomputed from its record would make the
correction history unverifiable — you could not tell an archived graph from a fabricated one.

`state digest` is the single hash of the current semantic layer. Two clean deployments of the
same fixtures must print the same value (Gate 4).

## 8. Check the graph

### Shapes

```sh
PYTHONPATH=src .venv/bin/python -m fhir_sulo.validation.cli shapes \
    --graph current.nt --strictness concept-note-literal
```
```
strictness   concept-note-literal
modules      base.ttl
result       conforms (concept-note-literal, 1 shape modules)
graph        220015 triples, 47566 focus nodes, digest 12953f289bd1199d
digest       c8c9568102d168eb…
```

**`--strictness` is required and there is no default.** Review item **R5** is open, and an
unanswered question must not quietly select the permissive answer — which is exactly what a
default did until DR-605. The choices are:

| value | meaning |
| --- | --- |
| `concept-note-literal` | R5 option B: shapes check only what the maps promise |
| `closed-world-complete` | R5 option A: quantities carry `isFeatureOf`, time instants carry a unit |
| `from-policy` | use the reviewer's recorded answer — **fails while it is unset** |

Omitting it is an argparse error; passing `from-policy` today exits 2 with the reviewer
question. Answering R5 means editing `src/fhir_sulo/validation/r5-strictness-policy.json` and
writing a decision record, not changing a default.

Violations print with a message naming the axiom or concept-note section they come from.

### Consistency and entailments

```sh
PYTHONPATH=src .venv/bin/python -m fhir_sulo.validation.cli reason \
    --graph current.nt -o reasoned.ttl
```
```
backend      docker obolibrary/robot:v1.9.7
consistency  consistent
asserted     780 triples
with entailments 2457 triples
```

An `INCONSISTENT` result is a hard stop.

**What this check does and does not catch.** The concept note §7 says "an OWL reasoner checks
consistency and expected PRO entailments". Precisely, on the graphs the maps emit today:

| | caught by |
| --- | --- |
| the PRO entailment `encounter hasParticipant person` is produced | **the reasoner** (verified two ways, DR-602) |
| a person typed as a `sulo:Quality` or `sulo:Role` | **SHACL only** — see below |
| a quantity with two values, a role with no holder, an orphan node | **SHACL** |
| a `hasPatient` shortcut | **SHACL and the negative queries** |

The second row is the one to know about. SULO has `Feature ⊑ Object` and
`Feature owl:disjointWith SpatialObject`. The maps type people as bare **`sulo:Object`**, and
`Quality ⊑ Feature ⊑ Object`, so a person *also* typed as a Quality or a Role is perfectly
consistent and the reasoner reports nothing. Had they been typed `sulo:SpatialObject` the
disjointness would make it inconsistent. So **there is no OWL guard against a misclassified
person under the current typing** — the SHACL disjointness shapes are what stops it, and they
run before the store, so nothing reaches the graph. Measured in
`test_reasoning_pro.py::R6EvidenceThePersonClassChoiceHasConsequences`; it is an input to open
review item **R6**, not an answer to it. DR-605 §3.

### Competency queries

```sh
PYTHONPATH=src .venv/bin/python -m fhir_sulo.validation.cli queries \
    --graph reasoned.ttl --reasoned \
    --systolic-class  https://example.org/fhir-sulo/SystolicBloodPressureQuality \
    --diastolic-class https://example.org/fhir-sulo/DiastolicBloodPressureQuality
```
```
PASS CQ1-egfr-for-person                38 row(s)
PASS CQ2-bp-pair-per-time               11 row(s)
PASS CQ3-encounter-participants         20 row(s)
PASS NQ1-no-cross-patient-result        0 row(s)
PASS NQ2-no-erroneous-status-assertion  0 row(s)
PASS NQ3-no-orphan-result               0 row(s)
PASS NQ4-no-hasPatient-predicate        0 row(s)

7/7 queries passed
```

Add `--rows` to see the answers, `--person <iri>` to ask CQ1 about one patient.

**`--reasoned` matters.** CQ3 asks who participated in an encounter, and under the PRO pattern
the *person* is a participant only by entailment. Run it on an unreasoned graph and it is
reported as a **failure**, with a note saying why — an unreasoned run must not be mistakable for
a passing one.

The `--systolic-class` / `--diastolic-class` IRIs are placeholders from the concept note. Review
item **R1** decides the real domain vocabulary; when it does, pass different IRIs. No query is
rewritten.

## 9. The benchmark

```sh
benchmarks/run.sh --strictness concept-note-literal   # 10,000 resources, 4 vCPU / 8 GB
benchmarks/engine_bench/run.sh                       # the pinned ShExMap engine
```

Constraints are applied by the script, not by you, and `--strictness` is required here too so a
report always names what it ran under. Last measured: **194 s, peak 2.14 GB** for 10,000
resources, against targets of 15 min and 6 GB.

**What that number does not include:** rendering, the real maps and the engine. It is a lower
bound, and it becomes the real end-to-end figure only when Agent 4's composed pipeline lands. Full protocol and caveats —
including what is *not* in that number — in [`benchmarks/README.md`](../../benchmarks/README.md).

## 10. Tests

```sh
make contracts                                   # Gate 0 interface guards, bare interpreter
make integration                                 # everything Agent 6 owns
PYTHONPATH=src:tests/integration .venv/bin/python -m unittest discover -s tests/integration
```

Tests needing `rdflib`/`pyshacl` or a reasoner **skip with a message** saying what to install,
rather than failing, so the contract tests still run on a bare interpreter.

## 11. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `REASONER UNAVAILABLE` | No `robot` on `PATH` and Docker is not running. Start Docker; the image is pulled on first use. |
| `reasoner-check` says `NOT USABLE` | The configured reasoner is not OWL 2 DL. Use HermiT (the default). Do not proceed. |
| `line N: LineageError: … parallel to the emitted quads` | The driver's `provenance[]` does not match `quads` one-for-one. Fix the driver — the store will not guess which quad lost its lineage. |
| `run … carries graph key … but its own fields hash to …` | The run record was edited after the fact, or built by something that does not compute the key from its own fields. |
| `… reuses a versionId … with a different JSON digest` | A FHIR server edited a resource in place. Version-based correction cannot work; report it upstream. |
| `graph … already holds different triples for the same key` | An input that changes triples is missing from the key. See `graph_key.CONTENT_FIELDS` and DR-601 — do not work around it. |
| `graph key input X is empty` | Record an explicit token such as `unresolved:R1`. An empty string and a real value must not hash alike. |
| `the following arguments are required: --strictness` | Correct behaviour. R5 is open, so a run must name the strictness it uses. Pick a value from the table in §8. |
| `R5 UNANSWERED: review item R5 is unanswered…` | You passed `--strictness from-policy` and the reviewer has not answered. Name an option explicitly, or record the answer in `r5-strictness-policy.json`. |
| Shapes fail only under `closed-world-complete` | Expected. R5 is open and that is one candidate answer; the maps do not emit those triples today. Do not "fix" it by changing the maps or the shapes. |

## 12. Where the decisions are

| Topic | Record |
| --- | --- |
| Graph key, correction semantics | [DR-601](decisions/DR-601-graph-key-and-correction-semantics.md) |
| Reasoner pin, PRO verification | [DR-602](decisions/DR-602-reasoner-pin-and-pro-verification.md) |
| SHACL choice, R5 switch | [DR-603](decisions/DR-603-shacl-for-target-validation.md) |
| R5 unset rejects; validation on map output | [DR-605](decisions/DR-605-r5-unset-rejects-and-validation-on-map-output.md) |
| Engine pin and its blockers | [DR-301](decisions/DR-301-engine-pin-and-capability-verdict.md) |
| One repetition per path | [DR-302](decisions/DR-302-one-repetition-per-path.md) |
| SULO pin and axioms | [DR-002](decisions/DR-002-sulo-pin-and-axioms.md) |
| Engineering deviations | [CONTRACT-DEVIATIONS.md](CONTRACT-DEVIATIONS.md) |
| Open clinical/ontology items | [REVIEW-REQUEST.md](REVIEW-REQUEST.md) |
