# FHIR to SULO: multiagent implementation plan

**Draft — 29 September 2026**  
**Companion:** [FHIR to SULO through ShExMap: concept note](FHIR_to_SULO_Concept_Note.md). This plan implements the concept note's clinical and ontological contract. It specifies parallel agent ownership and objective completion gates; it does not initiate production clinical deployment.

## 1. Deliverable and boundaries

Build a reproducible pilot that accepts **synthetic FHIR R4** resources, validates them against pinned profiles, renders FHIR RDF, applies reviewed ShExMap pairs, and emits a versioned SULO graph with provenance. The first supported mappings are numeric eGFR `Observation`, blood-pressure `Observation.component`, and `Encounter` with patient and clinician roles. `MedicationAdministration` follows after the core gates. R5 support is a separate compatibility track.

The reusable product has four parts:

1. **Mapping contracts:** source and target ShExMap schemas, fixture data, pivot-variable inventory, and map metadata published in the ShExMap Repository.
2. **Execution adapter:** an API/CLI that invokes a pinned ShEx.js engine build and receives bindings, target quads, analysis diagnostics, and per-quad lineage.
3. **Orchestration services:** FHIR import, reference and identity resolution, profile/map selection, terminology and UCUM policy, named graph updates, and PROV-O records. This can be packaged as a SULOizer FHIR module once its repository and deployment contract are confirmed.
4. **Conformance suite:** synthetic source/target fixtures, negative cases, pivot round-trip tests, semantic and reasoning checks, benchmarks, and CI.

The adapter must not reimplement graph-construction rules already expressed in ShExMap. No clinical data is required to pass the pilot gates.

### Proposed source layout

The layout is a contract for implementation; choose the repository after a read-only repository review. Avoid scattering generated graphs and mappings across unrelated codebases.

```text
docs/fhir-sulo/             decisions, mapping coverage, operator guide
maps/r4/                   versioned ShExMap source and SULO target schemas
profiles/                  pinned profile manifest and FHIR release
fixtures/r4/               synthetic JSON, canonical RDF, expected pivot trees
fixtures/expected/         expected SULO graphs and negative outcomes
src/fhir_sulo/             adapter and orchestration interfaces
tests/contracts/           engine and mapping conformance tests
tests/integration/         source-to-target and update tests
benchmarks/                synthetic generator and measurement protocol
```

Each mapping pair gets a manifest with `map_id`, semantic version, source release/profile, source/target shape labels, pivot variables and cardinalities, terminology dependencies, status eligibility, expected failures, SULO version, and fixture references. The repository's published pairing ID and immutable hash are included in every run record.

## 2. Agent roles and ownership

Six implementation agents can work concurrently after Agent 1 fixes the shared contracts. Each agent owns a disjoint area and submits a small reviewable change; integration and semantic review are separate responsibilities. An agent may inspect another area but changes it only through a reviewed interface request.

| Agent | Owns | Output and local success condition |
| --- | --- | --- |
| **1. Contract and integration lead** | `docs/fhir-sulo/`, manifests, shared types, CI gates, integration branch | Approved interfaces and scope; reproducible combined run; no interface drift between agents. |
| **2. FHIR ingestion** | `profiles/`, JSON validation/RDF rendering, source fixture capture | Each fixture retains release, canonical URL/version, profile, status, precise values, and resolvable reference context; source RDF round trips to its input content under the chosen renderer. |
| **3. ShExMap mapping author** | `maps/r4/`, pivot manifests, target shapes | eGFR, BP, and Encounter maps pass source and target checks; emitted triples use SOLID and PRO and contain no `hasPatient`. |
| **4. Engine and portability** | execution adapter, `tests/contracts/engine/` | Pinned ShEx.js build executes nested scopes, `id(...)`, static checks, alternatives, lineage, and update; feature differences in PyShEx/Rudof documented through the same fixtures. |
| **5. Identity and terminology** | identity/reference service, code/UCUM resolver, policy tables | Repeated references resolve to one intended person; ambiguous identity is rejected; unknown or incompatible codes/units have explicit outcomes; source codes are retained. |
| **6. Provenance, QA, and operations** | output graph/version store, PROV-O, target validation, reasoning, benchmark, run guide | Every derived graph is attributable, reprocessing is idempotent, corrections remove stale assertions, and all acceptance tests run in CI. |

The human ontology/clinical reviewer approves the domain typing and status policies before a map is marked usable. The lead reviews integration changes; another agent reviews each mapping for semantic mistakes. No agent may resolve a failed semantic test by weakening its expected graph without a recorded decision.

## 3. Shared interfaces fixed at Gate 0

### `SourceContext`

Contains `fhir_release`, canonical resource URL, version ID, declared and validated profiles, source JSON digest, RDF graph, resolved references with evidence, source status, terminology snapshot, and eligibility outcome. No person-equivalence claim is implicit in a resolved FHIR reference.

### `MapContract`

Contains pairing version/hash, source/target shape labels, variable names and types, repetition scopes, required values, allowed alternative shapes, static variables, node-key rules, inverse coverage, and expected nonmapped FHIR fields. `shexmap-check` or equivalent static analysis must pass before runtime.

### `TransformResult`

Contains target RDF quads, binding tree, target root, per-quad source binding/constraint lineage, diagnostics, status (`mapped`, `source-only`, or `rejected`), and deterministic output graph key. Only `mapped` output can be loaded into a clinical semantic graph. The caller must be able to inspect all binding alternatives rather than accepting an ambiguous map silently.

### `RunRecord`

Records source version/digest, map pairing/hash, SULO and domain ontology versions, terminology snapshot, engine build, policy version, activity time, graph key, validation report digest, and output digest. These are immutable metadata for the run, even when the current derived graph is replaced by a correction.

## 4. Sequence and dependency gates

### Gate 0 — freeze the pilot contract

**Lead with agents 2, 3, 5, and clinical/ontology reviewer.** Select the R4 profile set, exact mapping variables and node-key policy, domain classes, code systems, statuses, unknown-data rules, and three approved examples. Create fixtures before implementing the maps. Decide whether a quality IRI persists across observations or is observation-specific. Pin the SULO ontology and ShEx.js commit/package version.

**Pass when:** the manifest parses; fixtures and expected pivot tuples are committed; every required field has an explicit source, target, or rejection rule; the reviewer signs off on the record/fact distinction and PRO/SOLID target patterns.

### Gate 1 — independent engine and input spikes

**Agents 2 and 4 in parallel.** Agent 2 proves FHIR JSON → RDF for the fixtures and resolves references, including relative and contained references. Agent 4 executes a minimal map and probes nested repetitions, deterministic IDs, value constraints, mapping analysis, and error reports on the selected ShEx.js build. Agent 5 supplies a deterministic mock terminology/identity service.

**Pass when:** both spikes run from a clean checkout with pinned dependencies; two BP panels preserve their component pairing; running the same map twice yields the same graph identity; unsupported engine behavior is documented as a blocking issue rather than handled by a hidden postprocessor.

### Gate 2 — vertical slice: eGFR

**Agents 3, 4, 5, and 6.** Implement the source and target ShExMap pair, invoke it through the adapter, attach source/run provenance, and validate the target. Include normal numeric value, absent result, comparator, missing unit, wrong code, wrong patient reference, and `entered-in-error` variants.

**Pass when:** the normal fixture yields exactly one expected value/unit/quality/patient association; every negative fixture takes its specified `source-only` or `rejected` path; no source modification is lost; inverse validation recovers the shared pivot variables; there are no orphan quantity/unit nodes.

### Gate 3 — repeated BP and PRO encounter

**Agent 3 develops maps; Agent 4 tests engine scope behavior; Agent 6 tests target entailments.** Add two BP panels and an Encounter with patient and clinician roles and a bounded time interval. Test component omission, reordered RDF lists, duplicate values, another patient, and open-ended intervals. Map source record identifiers separately from semantic entities.

**Pass when:** the BP tuple multiset is exactly `{(bp-1,120,80),(bp-2,105,70)}` in the baseline fixture and all permutations preserve associations; a PRO-aware reasoner infers the correct patient and clinician as participants in the encounter; the graph contains no `hasPatient`; the inverse map recovers all shared bindings per scope.

### Gate 4 — correction, batch operation, and release candidate

**Agents 1, 2, 4, and 6.** Add deterministic batch processing, resumable failures, versioned graph replacement, run logs, and an operator guide. Test a source resource corrected from version 1 to version 2, a status changed to `entered-in-error`, and unchanged reprocessing. Run a synthetic scale trial. Publish reviewed map versions in the ShExMap Repository and pin their hash in the runtime configuration.

**Pass when:** unchanged reprocessing changes no triples; version 2 removes stale version-1 derived assertions from the current semantic graph while preserving version-1 lineage; an error status removes clinical assertions; a clean deployment produces identical graph hashes for the fixture suite. The benchmark processes 10,000 synthetic resources on a documented 4-vCPU/8-GB runner within 15 minutes, with peak memory below 6 GB and no unexpected mapping failures. These are pilot engineering targets, to be revised only by an explicit performance decision backed by measured profiles.

### Gate 5 — extension and portability

After the core release, add `MedicationAdministration` with its `subject`, `performer`, dose/unit, route, and effective time, preserving the distinction between medication code and an identified physical drug. Add an R5 adapter for the same semantic contract. Run the same fixtures against PyShEx and Rudof where their mapping APIs support them; record exact feature and output differences. No portability result is inferred solely from successful ShEx validation.

**Pass when:** medication process, roles, dose, route, and time are independently queryable and correctly associated; all source codes and uncertainties remain accessible; R4 and R5 inputs matching the approved clinical meaning yield equivalent SULO pivot graphs; portability findings identify engine version and any unsupported features.

## 5. Acceptance matrix

| Contract | Test | Success condition |
| --- | --- | --- |
| Source fidelity | JSON → FHIR RDF → source comparison | All mapped fields, cardinalities, codes, comparators, statuses, and temporal precision survive. An unsupported modifier extension blocks semantic materialization. |
| SOLID | eGFR target shape and query | One `sulo:Quantity` has one numeric `hasValue`, correct unit, and `refersTo` a quality `isFeatureOf` the correct person. No fabricated measurement process or diagnosis. |
| Repetition | Two BP panels with permutation/duplicate-value cases | Correct within-panel systolic and diastolic pairing; no cross-panel joins or accidental coalescence. |
| PRO | Encounter target plus reasoner | Typed roles belong to correct holders and process; expected direct participation is inferred; no `hasPatient` predicate. |
| Status/absence | Error, absent reason, comparator, incomplete record | Exactly the declared `mapped`, `source-only`, or `rejected` result. No unqualified numeric assertion. |
| Identity | Replay, another patient, unresolved/ambiguous references | Deterministic entity keys on replay; distinct people remain distinct; ambiguous identity never silently merges. |
| Mapping analysis | Static schema check and negative schemas | Unbound variables, incompatible repetition scopes, and invalid `id()` uses fail before data processing. |
| Pivot reversibility | Validate target output against inverse map | Same shared variable/value pairs and repeated tuple multiset after forward/backward mapping. No promise of full FHIR reconstruction. |
| Lineage | Inspect every output quad and run record | Every quad traces to a source binding/constant plus source resource version, map hash, and run activity. |
| Correction | Version 1 → 2 → entered-in-error | Current graph has only eligible current assertions; earlier versions and run records remain auditable. |
| Deployability | Clean build and fixture run | One documented command runs CLI/API and CI tests with pinned versions; no JVM dependency introduced for the mapping stack. |
| Scale | Synthetic 10,000-resource run | Meets Gate 4 time/memory limits, stable output counts, and reports failure categories and throughput. |

In addition to shape validation, competency queries must answer: **Which eGFR result, value, unit, and time was reported for this person? Which systolic/diastolic pair belongs to each encounter time? Who participated in this encounter and in which role?** Negative queries must find no cross-patient results, erroneous-status clinical assertion, or orphan result.

## 6. Agent coordination protocol

1. **Lead posts the contract first.** Agents use the same fixture IDs, prefix declarations, SULO version, and `MapContract` schema. Contract changes are reviewed before downstream edits.
2. **One owner per path.** Agents work in separate branches or worktrees; integration lead merges in gate order. Map authors do not edit the engine adapter to make a failed fixture pass; engine authors do not alter the ontology mapping to hide an engine failure.
3. **Each PR carries evidence:** scope, map or engine version, fixture inputs, expected graph diff, validation/competency results, unresolved semantics, and affected contract fields.
4. **Independent review:** ontology/clinical reviewer checks meaning; a different technical agent checks code, data fidelity, and negative cases. Any disagreement becomes a decision record with an example graph.
5. **Gate before expansion:** no new FHIR resource family starts until the current vertical slice and its negative cases pass. Do not run all workstreams against a moving source profile or engine commit.
6. **Integrate once per gate:** lead runs the full suite from a clean checkout and tags the passing map/engine combination. A failed gate returns to its owning agent with a minimal reproducer.

The agent split permits work in parallel while the fixture/contract gate prevents incompatible assumptions from propagating. The implementation need not use six agents if fewer are available; keep ownership and independent review even when roles are combined.

## 7. Main risks and decisions

| Risk | Mitigation / decision owner |
| --- | --- |
| FHIR RDF conversion or reference links change the source graph | Pin renderer and release; compare JSON and RDF fields; Agent 2 owns fixtures. |
| ShEx.js main-branch feature differs from installed package | Pin exact build; Agent 4 runs feature probes before Agent 3 depends on them. |
| Repeated components lose association | Binding-tree and tuple-multiset tests at Gate 1 and Gate 3; never flatten to independent value bags. |
| Observation code is treated as an unconditional fact or class | Reviewed code interpretation table; preserve record separately; clinical reviewer owns semantic approval. |
| Unknown patient identity merges two people | Conservative scoped identifiers, evidence for cross-resource merging, reject ambiguity; Agent 5 owns policy. |
| A corrected FHIR resource leaves stale semantic triples | Deterministic per-resource graph key and replace/remove procedure; Agent 6 owns correction tests. |
| Meaning depends on modifier extension, status, or comparator | Explicit eligibility/variant manifest with negative fixtures; unknown variants are source-only or rejected. |
| License/access to real clinical data | Synthetic data through pilot; subsequent clinical evaluation requires site-specific governance and validation. |

## 8. Definition of done

The pilot is complete when Gates 0–4 pass from a clean checkout, all fixtures and negative cases are versioned, mappings are published with immutable identifiers, the SULO graph and lineage are reproducible, the clinical/ontology reviewer signs off on the approved interpretations, and an operator can run and inspect a batch without editing code. Gate 5 is the next scoped release, not an unstated condition of the initial pilot.

## Primary references

- [FHIR R4 RDF](https://hl7.org/fhir/R4/rdf.html), [Observation](https://hl7.org/fhir/R4/observation.html), [Encounter](https://hl7.org/fhir/R4/encounter.html), [MedicationAdministration](https://hl7.org/fhir/R4/medicationadministration.html), and [Provenance](https://hl7.org/fhir/R4/provenance.html).
- [SULO ontology](https://github.com/AIDAVA-DEV/sulo) and [SOLID/PRO paper](https://ceur-ws.org/Vol-4176/foust-7.pdf).
- [ShEx.js ShExMap iteration-scope documentation](https://github.com/shexjs/shex.js/blob/main/packages/extension-map/doc/iteration-scopes.md) and [ShEx.js CLI](https://github.com/shexjs/shex.js).
- [ShExMap Repository](https://github.com/micheldumontier/shexmap-repository), [PyShEx](https://github.com/linkml/PyShEx), and [Rudof materialization](https://rudof-project.github.io/rudof/cli_usage/materialize.html).
