# `maps/r4/` — the reviewed ShExMap pairings

Owner: Agent 3 (mapping author). Rationale: [DR-201](../../docs/fhir-sulo/decisions/DR-201-map-architecture-and-shexmap-limits.md).

Three pairs, one per worked example in the concept note:

| Directory | `map_id` | Concept note |
| --- | --- | --- |
| `egfr/` | `fhir-r4-egfr-solid` | §4, SOLID quantity |
| `bp/` | `fhir-r4-bp-panel-solid` | §5, two blood-pressure panels |
| `encounter/` | `fhir-r4-encounter-pro` | §6, PRO roles |

## Four files per map

| File | What it is |
| --- | --- |
| `<f>-source.v1.shex` | the FHIR R4 source shape. Rooted at one resource, all shapes `CLOSED`. |
| `<f>-target.v1.shex` | the SULO target shapes. Only SULO 0.2.12 terms and `prov:` appear literally. |
| `<f>-bindings.v1.json` | **the run-binding manifest: the single indirection point.** |
| `<f>-map-contract.v1.json` | the `MapContract` (plan §3), deserialised by the tests into the frozen dataclass. |

`maps/r4/rehash.py --check` recomputes each contract's `pairing_hash` over its three pairing
files and fails on drift, so a schema edit that leaves the hash alone fails the build.

## The two rules that shape everything here

**One rooted pass per IRI-identified target node.** The pinned engine gives one controllable
IRI per materialization — the root — and has no `id()` (DR-301 §4b/§4c, CD-1). Each node that
needs a stable IRI is therefore the root of its own pass, referring to its neighbours as leaf
IRIs supplied through `staticVars`. All passes of one map share a single source validation. No
blank node appears in any output.

**Every target triple constraint is required.** Optionality lives in *which passes run*
(`requires_source_binding` / `forbids_source_binding` in the bindings manifest) and in
alternative entry shapes. So `lastReport.unboundVariables != []` is always an error, which is
the only detector for DR-301 blocker 8c — a silent partial graph with exit 0 and a clean
stderr. An optional target constraint was measured and rejected; see DR-201 §2.

## The indirection point

**No domain class IRI, person IRI or quality IRI appears in any `.shex` file.** Every one is a
`staticVars` run binding named in `<f>-bindings.v1.json`, which records where each value comes
from and which review item governs it:

| Review item | Manifest key |
| --- | --- |
| R1 domain vocabulary | `vocabulary.*.iri`, `domain_namespace.value` |
| R2 quality identity | `identity_provided.*Quality` → `policies/identity-policy.v1.json` |
| R4 `sulo:Quality` vs `sulo:Feature` | `vocabulary.qualityBranch.iri` |
| R6 person SULO parent | `vocabulary.personSuloClass.iri` |
| R8a practitioner entity kind | `vocabulary.clinicianClass.iri` |
| R9 BP panel typing | `not_emitted.panelClass` |

`tests/contracts/maps/test_map_contracts.py` asserts the manifests mirror the policy tables
rather than holding a second opinion, and that no schema names the placeholder namespace.

## Acceptance conditions are asserted on the emitted graph

Not on the source bindings. The target graph is what reaches a clinical store,
and a map can bind the right values and emit the wrong ones — which is exactly
what happened, and is why
[DR-203](../../docs/fhir-sulo/decisions/DR-203-the-acceptance-check-was-on-the-wrong-artifact.md)
exists. `tests/contracts/maps/_engine/graph.py::bp_panel_tuples` recovers the
blood-pressure multiset by walking the emitted graph and reads no binding at
all; it takes N-Triples as a **string**, so the producer is swappable between
this harness, Agent 4's driver and a file on disk.

Source-side comparisons against Agent 2's `expected-bindings.json` are kept as
named corroboration (`BPSourceBindingMultiset`): they localise a fault to the
extraction half, which a target-side check alone would misattribute.

## Running them

The maps are driven through `ThreadedMaterializer`, never the shipped CLI (CD-2). Until Agent
4's driver lands, `tests/contracts/maps/_engine/` holds a test-only harness that does the same
thing: `shex-validate` for binding extraction, the API with `maxAccepts`/`maxRepeat`/
`maxSteps`/`exploreSteps` raised for materialization.

```bash
make venv
PYTHONPATH=src .venv/bin/python -m pytest tests/contracts/maps -q
```

Needs Docker; the engine runs in `node:20-bookworm-slim` and the tree is shipped in with
`docker cp`, because Colima shares only the VM owner's home.

## Status

Nothing here is clinically signed off. Every code and unit used carries
`review_status: pilot-provisional`, and R1, R2, R4, R5, R6 and R9 are all open. DR-201 §8 lists
where each answer lands; none of them requires re-authoring a schema.
