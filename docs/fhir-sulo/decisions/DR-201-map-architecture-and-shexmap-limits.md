# DR-201 — Map pair architecture, and what ShExMap could not express

**Status:** Decided (engineering) + **three new items referred to the reviewer**
**Date:** 2026-09-29
**Gate:** 2 / 3
**Owner:** Agent 3 — ShExMap mapping author
**Amended by:** DR-203 (the Gate 3 acceptance check was on the wrong artifact)
**Depends on:** DR-301 (engine pin and capability verdict), DR-302 (one repetition per path),
CD-1 (no `id()`), DR-002 (SULO 0.2.12 axioms), DR-102 (fixture and binding-tuple format)
**Implements:** concept note §2, §4, §5, §6, §7

Three map pairs are delivered in `maps/r4/`:

| Map | `map_id` | Source shape | Entry target shapes | Fixtures |
| --- | --- | --- | --- | --- |
| eGFR (§4) | `fhir-r4-egfr-solid` | `sh:EGFRObservation` | 6 | 10 |
| Blood pressure (§5) | `fhir-r4-bp-panel-solid` | `sh:BPObservation` | 10 | 5 (× 2 resources, × 2 RDF variants) |
| Encounter (§6) | `fhir-r4-encounter-pro` | `sh:ClinicalEncounter` | 9 | 4 |

Each pair is a source `.shex`, a target `.shex`, a run-binding manifest and a `MapContract`
manifest, all versioned `v1` and bound together by a `pairing_hash` that
`maps/r4/rehash.py --check` enforces.

---

## 1. One rooted pass per IRI-identified target node

The engine gives exactly one controllable IRI per materialization: the root
(DR-301 §4c). Every other node it creates is a blank node, and a Map variable on a
shape-valued constraint emits the bound IRI as a *leaf* and drops the sub-shape
entirely (§4b). There is no `id()` (CD-1).

The concept note's target graphs have six to nine IRI-named nodes each. So:

> **Each IRI-identified target node is the root of its own materialization pass, and refers to
> its neighbours as leaf IRIs supplied through `staticVars`.** All passes of one map consume the
> *same* binding tree from a single source validation; only the root and the entry shape change.

This is DR-302's decomposition with the join key moved to the target side. The host chooses
roots and unions passes — both actions concept note §3 already assigns it — and constructs no
triple. `tests/contracts/maps/test_expected_graphs.py::test_every_emitted_predicate_is_written_in_a_target_schema`
asserts that for all 19 fixtures.

Consequence worth stating: **no blank node appears in any output graph.** Every node has an
IRI whose key rule is declared in `MapContract.node_key_rules`, which is what Gate 4's
"a correction removes stale derived assertions" needs, and it sidesteps DR-301 §4d's
blank-node-collision hazard entirely rather than relying on relabelling.

## 2. Every target triple constraint is required

Optionality — `bp-component-omitted` has no diastolic component — is expressed by **which
passes run**, declared per pass in the run-binding manifest as `requires_source_binding` /
`forbids_source_binding`, and by **two alternative entry shapes** where a node's arity changes
(`MapContract.allowed_alternative_shapes`).

**Measured, not assumed.** An optional target constraint works — with
`sulo:refersTo IRI ? %Map:{ v:diaResult %}` and `diaResult` unsupplied the engine emits exactly
the right graph — but it *still* lists `diaResult` in `lastReport.unboundVariables`. That
destroys the only available detector for DR-301 blocker 8c, where an unbindable target variable
silently prunes branches and yields a partial graph with exit 0 and a clean stderr. With every
constraint required, the rule is unconditional:

> a non-empty `lastReport.unboundVariables` is always an error.

The tests assert that, plus `unusedStatics == []` and `alternatives == 1`, on every pass of
every fixture.

## 3. Blood-pressure components are discriminated by LOINC code, not by repetition

`fhir:Observation.component` carries two triple constraints, one per component shape, each
pinned to its own `Coding.code` value set. Neither repeats. The BP map therefore has **zero**
repeating constraints on any path from the root, strictly inside DR-302 rather than at its
limit.

Why this is the right reading and not a dodge:

- DR-102 already states the contract as code-discriminated: "Components are selected by LOINC
  code, not by position", and Agent 2's `expected-bindings.json` names the variables `sys` and
  `dia` rather than indexing a repeated group.
- It makes the concept note §5 requirement **structural**. `(bp-1,120,80)` cannot become
  `(bp-1,120,70)` because 70 lives in a different resource and therefore a different engine
  run; and it cannot become `(bp-1,80,120)` because 80 is bound by the constraint whose code is
  `8462-4`, whatever the triple order and whatever `fhir:index` says. The
  `bp-reordered-serialisation` fixture's components-reversed variant is a genuinely different
  graph (the `fhir:index` values move) and yields the same tuples.
- DR-301 probe 3 already demonstrated that the one-level repetition route also works. This
  route is strictly safer and matches the declared binding contract.

**Cost, recorded:** a BP panel with a third component, or any code outside
`{8480-6, 8462-4}`, fails validation loudly. Enumerating component codes does not scale to an
open panel. A panel with more members would need the one-level repetition form, and then each
member's target IRI and quality IRI would have to vary per iteration — which is the limitation
in §5 below.

## 4. Guards are CLOSED shapes, so nothing is dropped silently

Every source shape is `CLOSED`, with `fhir:DomainResource.contained . *` tolerated and never
mapped. Concept note §2 forbids dropping "a comparator, absent-value reason, method, unit
code/system, component association, or a modifier extension while claiming an unqualified
numeric result"; a CLOSED shape turns every one of those into `shex-validate` exit 1 with a
parseable `Failure`, which DR-301 probe 8a confirms is the engine's well-behaved path.

Concretely, `egfr-comparator` fails because `sh:EGFRQuantity` is CLOSED and declares no
`fhir:Quantity.comparator`. Removing that one word makes the fixture materialize an unqualified
`55.0`, and `fixtures/expected/build.py --check` catches it — verified by fault injection.

## 5. What ShExMap could not express

Reported rather than worked around, per the standing instruction.

### 5.1 More than one Encounter participant (v1 restriction, real limitation)

`fhir:Encounter.participant` is cardinality **1** in `encounter-source.v1.shex`. A second
participant fails validation.

The blocker is not repetition — one level works. It is that each participant needs its own
role node IRI *and* its own role-holder IRI, both of which are identity-service outputs
supplied as `staticVars`, and **`staticVars` are global to a materialization**: the engine's
`cursorGet` treats them as "always available, never consumed", so there is no way to give
iteration *i* a different clinician IRI. DR-302's decomposition does not rescue it either,
because a FHIR `participant` is a blank node in the RDF with no source IRI to root a pass at.

Options, none taken unilaterally:

- **A.** Skolemize participants host-side and root a pass per participant at the skolem IRI.
  Needs an owner for the skolemization rule; closest to DR-302's pattern.
- **B.** Have the identity service mint a role IRI per (encounter, participant index,
  entity), and pass N times with N single-participant binding subsets. Needs Agent 5 to own
  participant-scoped keys.
- **C.** Leave it at one participant for the pilot and revisit at Gate 5.

The same shape of problem will hit any resource with a repeated group whose members need
distinct minted IRIs — which includes `MedicationAdministration.dosage` and, per CD-3, anything
Bundle-rooted.

### 5.2 A node that receives arcs from two passes cannot revalidate against one entry shape

If pass A emits `panel refersTo sysResult` and pass B emits `panel refersTo diaResult`, the
panel node has two `sulo:refersTo` arcs while either entry shape declares one, so validating
the materialized graph against its own target schema fails with `ExcessTripleViolation` and
pivot recovery (concept note §5) breaks.

`EXTRA sulo:refersTo` does **not** fix it: `shex@1.0.0-alpha.33` excuses only an arc that
*fails* the constraint, not a surplus arc that satisfies it. Measured.

Resolution: every arc of one predicate on one node is emitted by **one** shape, with alternative
entry shapes where the arity varies (§2). Recorded because it constrains how any future map
may be decomposed.

### 5.3 Two variable-bound `rdf:type` constraints are indistinguishable in reverse

A node typed `rdf:type IRI %Map:{ v:qualityBranch %} ; rdf:type IRI %Map:{ v:qualityClass %}`
materializes correctly, and the reverse direction recovers the correct **set** of classes with
an **arbitrary assignment** of classes to variables: the inverse cannot tell two same-predicate
IRI constraints apart. Nodes whose second `rdf:type` is a constant value set —
`[sulo:Quantity]`, `[sulo:Role]`, `[sulo:Process]` — are unaffected.

This is the price of keeping the SULO branch parameterised for R4 and the person parent
parameterised for R6, and the brief requires that parameterisation. The affected variables are
recorded `inverse_covered: false` in each `MapContract`, and
`test_inverse_pivot.py::test_two_variable_bound_rdf_types_recover_as_a_set_not_a_mapping`
asserts both halves — the set is right, the mapping is not — so the day it changes, the
contract gets updated rather than quietly drifting.

The same ambiguity affects the panel record's two `sulo:refersTo` arcs. The
systolic/diastolic association is therefore recovered from the **quantity nodes**, which carry
distinct domain types and distinct quality referents, and `test_inverse_pivot.py` asserts the
full `{(bp-1,120,80),(bp-2,105,70)}` multiset that way.

### 5.4 No string construction, so derived IRIs are host-chosen roots

`{canonical_url}/_history/{versionId}` and `{domain}egfr-result-{obsId}` cannot be built by the
engine — it has `hashmap`, `regex` and `test`, and an unknown Map function silently deletes the
whole shape. They are declared in `MapContract.node_key_rules` and applied by the host when it
picks a root, which CD-1 names as the substitute. **Gap: Agent 5's identity service mints
person and quality IRIs but not result, record, role, interval or time node IRIs.** Those five
rules currently live in this agent's manifests. They should move behind the identity service so
one component owns node identity; raised with the integration lead.

## 6. Two consequences for sequencing that were not obvious

- **Answering R1 re-keys every quality IRI**, not just R2. `quality_class_iri` is one of the
  quality key inputs in `policies/identity-policy.v1.json`, so swapping the domain vocabulary
  moves every quality node. Asserted in
  `test_egfr_gate2.py::test_the_domain_vocabulary_can_be_swapped_without_touching_a_schema`,
  which also proves nothing else moves.
- **A contained reference is scoped to its container.** `enc-12`'s `#pr-inline` practitioner is
  a different entity from `enc-9`'s `Practitioner/c7`, and two Observations each containing a
  Patient `#p` do not merge. The host currently supplies that scoping to Agent 5 as part of
  `SourceScope.scope_id`; Agent 2 proposed the same rule in its `MockIdentityService`. It
  belongs inside the identity service, not in every caller.

## 7. New items for the consolidated review request

Referred to Agent 1 for `REVIEW-REQUEST.md`; **not** started as a second list, and none treated
as resolved.

- **N1 — How does a BP panel record relate to its component results?** The maps use
  `sulo:refersTo`, mirroring §4's `ex:egfr-record-456 sulo:refersTo ex:egfr-result-456`.
  `sulo:hasPart` (the panel is *composed of* its components) is equally defensible and gives a
  different graph. Concept note §5 says only "relates to both component results".
- **N2 — What class is the Encounter record?** §4 names `ex:ObservationRecord` but §6 names no
  class for the Encounter's record layer. The maps emit `ex:EncounterRecord` as a placeholder.
  Subsumed by R1 if R1 mints a vocabulary, but it needs an entry either way.
- **N3 — Should the FHIR participation type map to a role class?** `v3-ParticipationType PPRF`
  is bound and guarded but types nothing, because there is no reviewed
  participation-type-to-role-class table; `ex:ClinicianRole` comes from the vocabulary instead.
  A reviewed table would be the natural home, and would also decide what `SBJ`, `ATND` and the
  rest become.

## 8. Reviewer answers that are configuration changes, as required

| Item | Where the answer lands | Re-authoring? |
| --- | --- | --- |
| R1 domain vocabulary | `*-bindings.v1.json` `vocabulary.*.iri` | no (but re-keys qualities) |
| R2 quality identity | `policies/identity-policy.v1.json` `quality_identity.mode` | no (re-keys qualities) |
| R4 `Quality` vs `Feature` | `vocabulary.qualityBranch.iri` | no |
| R5 explicit `isFeatureOf` / time unit | one triple constraint per target shape + one manifest entry | one-line schema edit |
| R6 person SULO parent | `vocabulary.personSuloClass.iri` | no |
| R9 panel code types the panel | `not_emitted.panelClass` becomes a `vocabulary` entry + one constraint | one-line schema edit |
| R3 status policy | `status_eligibility` value sets in the source schemas | value-set edit |
| R8a practitioner entity kind | `vocabulary.clinicianClass.iri` (already a separate entry) | no |
