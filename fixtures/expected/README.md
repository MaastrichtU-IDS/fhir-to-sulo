# `fixtures/expected/` — expected SULO target graphs and negative outcomes

Owner: Agent 3 (mapping author). Rationale and the full outcome matrix:
[DR-202](../../docs/fhir-sulo/decisions/DR-202-expected-graphs-and-negative-outcomes.md).

One directory per Agent 2 fixture, mirroring `fixtures/r4/`:

```
fixtures/expected/<family>/<fixture-id>/
    outcome.json   the map's outcome, cross-checked against Agent 2's declared eligibility
    target.nt      GENERATED  the expected SULO graph, sorted N-Triples (only where it maps)
```

All 19 fixtures are covered. **Nine materialize; ten produce no graph, and all ten agree with
Agent 2's declaration** — six `rejected`, four `source-only`. No disagreements.

## Regenerating

```bash
python3 fixtures/expected/build.py           # write
python3 fixtures/expected/build.py --check   # verify; exit 1 on drift
```

Both run the pinned engine in Docker. `tests/contracts/maps/test_expected_graphs.py` runs
`--check`.

## These are regression evidence, not the acceptance conditions

`target.nt` is generated and then reviewed. It catches drift in the maps, and it catches a
change in another agent's component, because it contains the identity service's literal entity
and quality IRIs.

The acceptance conditions are hand-written invariants in `tests/contracts/maps/`:

| File | Asserts |
| --- | --- |
| `test_egfr_gate2.py` | one value / unit / quality / patient association, no orphan nodes, the SULO axioms, the R1 swap |
| `test_bp_gate3.py` | the `{(bp-1,120,80),(bp-2,105,70)}` multiset on every fixture and both RDF variants, no `hasPatient`, and four fault injections |
| `test_encounter_gate3.py` | the PRO entailment holds *and* is not asserted directly |
| `test_inverse_pivot.py` | target-to-source pivot recovery |

None of them reads this directory, so a wrong graph regenerated here still fails them.

## `outcome.json`

```jsonc
{
  "declared_by_agent2": "eligible | source-only | rejected",   // from fixtures/r4/.../case.json
  "map_outcome": "mapped | source-shape-nonconformant | identity-rejected",
  "agrees_with_agent2": true,
  "diagnostic": { ... },          // the ShEx Failure's elements, or the identity reason code
  "run_parameters": { ... }       // see below
}
```

Every negative carries a diagnostic. A silent rejection would be the same failure class
DR-301 warns about.

## The graphs depend on two unanswered review items

Recorded in every `run_parameters`:

- **R2 quality identity** is unanswered and the shipped default *rejects every request*. The
  graphs are generated with `quality_identity_mode: "per-observation"`, set explicitly.
  Answering R2 moves every quality IRI here and nothing else.
- **R1 domain vocabulary** is a placeholder with no owner. Answering it also moves every
  quality IRI, because `quality_class_iri` is one of the quality key inputs.

Nothing here is clinically signed off.
