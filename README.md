# FHIR to SULO

A reproducible pilot that takes **synthetic** FHIR R4 resources, validates them against pinned
profiles, renders FHIR RDF, applies reviewed ShExMap pairs, and emits a versioned SULO graph
with provenance.

Two documents are the scope and acceptance contract for everything here:

- [Concept note](docs/FHIR_to_SULO_Concept_Note.md) — the semantic and technical contract
- [Multiagent implementation plan](docs/FHIR_to_SULO_Multiagent_Implementation_Plan.md) — work
  packages, shared interfaces and the Gate 0–5 pass conditions

> **Status: Gates 0–4 are engineering-complete and awaiting clinical/ontology review.**
> Every gate's mechanical conditions pass. Gate 0 is blocked on human sign-off, and by the
> plan's own ordering rule every later gate is correctly held behind it. **Nothing in this
> repository is approved for clinical use, and no output is clinically signed off.**

## Quick start

```bash
make venv                 # pinned dev + runtime dependencies
make contracts            # full test suite (pytest, authoritative)
make contracts-stdlib     # same invariants, standard library only, no install

# These need Docker (the ShEx.js engine and the OWL reasoner run in pinned containers)
make engine-live          # engine probes and host tools, live engine REQUIRED
make lint-schemas         # static analysis of every committed ShExMap pair
./benchmarks/run.sh       # 10,000 synthetic resources under Gate 4's limits

FHIR_SULO_REQUIRE_ENGINE=1 FHIR_SULO_ENGINE_TESTS=1 python3 tools/gate-check.py --all --report
```

`tools/gate-check.py` encodes the plan's per-gate pass conditions as executable checks, so
advancing a gate is a verifiable event rather than a claim. A condition with no mechanical
check reports `MANUAL` and **blocks**; a check that raises reports `FAIL`. Gates advance in
order, so a later gate reports `HELD`, never `PASSED`, while an earlier one is blocked.

## Layout

| Path | Contents |
| --- | --- |
| `docs/fhir-sulo/` | decision records, contract deviations, operator guide, review request |
| `profiles/` | pinned FHIR release, profile set and element table |
| `maps/r4/` | the three ShExMap pairs (eGFR, blood pressure, Encounter) and their contracts |
| `fixtures/r4/` | 19 synthetic fixture cases, canonical RDF, expected pivot tuples |
| `fixtures/expected/` | expected SULO graphs and negative outcomes |
| `src/fhir_sulo/` | ingestion, identity, terminology, engine driver, store, provenance, validation |
| `tools/engine/` | the pinned ShEx.js engine, its probes, and the schema-pair linter |
| `tests/`, `benchmarks/` | contract, integration and scale checks |

## Key constraints worth knowing before you change anything

- **One repeating constraint per path, and every map is rooted at a single FHIR resource**
  ([DR-302](docs/fhir-sulo/decisions/DR-302-one-repetition-per-path.md)). At two levels the
  engine silently mis-associates groups and drops members; it is upstream's specified
  behaviour, not a bug we can report. The linter enforces this and fails the build.
- **The engine CLI is banned.** It truncates repetitions to 19 items and exits 0 on fatal
  errors. Materialization goes through the `ThreadedMaterializer` API with guards set
  explicitly ([CD-2](docs/fhir-sulo/CONTRACT-DEVIATIONS.md)).
- **There is no `id()`** in the pinned engine, and an unknown Map function silently deletes the
  shape that used it. Node identity comes from source IRIs plus the identity service
  ([CD-1](docs/fhir-sulo/CONTRACT-DEVIATIONS.md)).
- **Target triple construction lives in the ShExMap schemas.** The host selects roots, sequences
  passes and unions named graphs; it emits no triple of its own, and a test asserts that.

## Review

[`docs/fhir-sulo/REVIEW-REQUEST.md`](docs/fhir-sulo/REVIEW-REQUEST.md) holds 12 open clinical
and ontology questions. **None is approved.** Where an item is unresolved the affected output is
held at `source-only` or `rejected` with a diagnostic naming the item, so no unqualified
assertion escapes while a question is open.

## Data and licence

All patient data here is **synthetic**. Licensed under the Apache License 2.0 — see
[LICENSE](LICENSE), and [NOTICE](NOTICE) for redistributed third-party content (the SULO
ontology under MIT, HL7 FHIR R4 examples under CC0).
