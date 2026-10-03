# DR-403 — IR-603: one owner for node identity (proposal, not yet implemented)

**Status:** **PROPOSED — awaiting the integration lead.** No code in this DR is written.
**Date:** 2026-10-03
**Gate:** debt from Gates 0–4; blocking for Gate 5
**Owner:** Agent 5 — identity and terminology
**Addresses:** DR-007 §4 IR-603; DR-201 §5.1 and its options A/B/C; CD-1 (no `id()` in the
pinned engine)

## 1. What is actually split — four surfaces, not two

IR-603 says "Agent 5's service mints person and quality IRIs; result, record, role, interval
and time IRIs are minted from rules in Agent 3's map manifests." That is true but understates
it. There are **two artefacts both called node key rules, and only one is executable**:

| | `node_key_rules` | `node_keys` |
| --- | --- | --- |
| file | `maps/r4/<fam>/<fam>-map-contract.v1.json` | `maps/r4/<fam>/<fam>-bindings.v1.json` |
| placeholders | `{domain_namespace}`, `{Observation canonical url}` — **prose** | `{domain}`, `{canonicalUrl}` — real `str.format` fields |
| read by `src/` | **nothing** | `Manifest.node_keys()` → `families.resolve()` → `build_passes()` → engine |

Verified: `grep -rn node_key_rules src/` returns exactly one hit, its own declaration at
`src/fhir_sulo/contracts/map_contract.py:90`. Its only other reader is
`tests/contracts/maps/_engine/contractio.py:61`, which loads it and asserts nothing about it.

`MapContract.node_key_rules` is therefore **dead code that reads as coverage** — the same
defect category DR-007 recorded against `check_bp_multiset_live`. It is a free-form
`Mapping[str, str]` with no validation in `__post_init__`, and it mixes executable templates
with prose descriptions of service calls:

```json
"result":  "{domain_namespace}egfr-result-{obsId}",
"person":  "fhir_sulo.identity.IdentityService.resolve(Observation.subject).entity_iri",
"quality": "fhir_sulo.identity.IdentityService.resolve_quality(...).quality_iri  [R2 governs the key inputs]"
```

Nothing checks either half against reality. Edit it and no test notices.

The live split:

| node kind | minted by | rule lives in |
| --- | --- | --- |
| `result`, `record`, `panelRecord`, `sysResult`, `diaResult`, `process`, `patientRole`, `clinicianRole`, `interval`, `startTime`, `endTime`, `timeInstant`, `sourceVersionIri` | `Manifest.node_keys()` — `str.format` | `maps/r4/*/*-bindings.v1.json` |
| `person`, `clinician` | `IdentityService.resolve` — sha256 of 6 declared fields | `policies/identity-policy.v1.json` |
| `quality`, `sysQuality`, `diaQuality` | `IdentityService.resolve_quality` — sha256 of 6 or 9 fields | same |
| `unitIri` | `TerminologyService.resolve_unit` | `policies/unit-policy.v1.json` |

Both already travel down the same wire: `families.py` puts every one of them into one flat
`values` dict, and `runner.build_passes()` splits it into the pass root and `staticVars`. So
**there is nothing structural to change in the engine call.** The only question is which
component fills which key.

## 2. The recommendation, in one line

> **The identity service should own the node-identity *scheme*, its execution and its
> validation. The manifests should keep the *declarations*. It should not mint all node IRIs
> itself.**

### Why not "mint everything"

Collapsing both mechanisms into the hashing one would mean either:

- hashing `result` / `record` / `timeInstant` too — which destroys the readability DR-005 §1
  chose deliberately ("an expected-graph fixture full of these is not reviewable by a human,
  and the reviewer has to check those graphs"), moves every golden graph, and breaks the
  ~15 test files that name a minted IRI literally; or
- growing a template engine inside `IdentityService` — two services in one trenchcoat.

The two mechanisms differ for a reason that is not accidental:

- A **template** IRI is a *derived name*. `egfr-result-egfr-456` is a function of the source
  resource's own identity. It is readable on purpose, and `test_egfr_gate2.py::CorrectionReplacesTheSameNodes`
  depends on it being keyed on the resource id and **not** the version, so v1→v2 reuses the
  same nodes.
- An **entity** IRI is an *identity decision*. It needs evidence, a scoping policy, ambiguity
  rejection and an auditable `DecisionRecord`. It is hashed because its key inputs are a
  reviewed tuple, not a name.

### So what is actually broken

Not "two minters". The real defect is that **no component owns node identity as a concept**:

1. nothing can answer "what is the IRI of node *X* for input *Y*" without knowing which of two
   mechanisms applies;
2. nothing validates that every declared node key is produced, or that two node kinds cannot
   collide;
3. — the Gate 5 blocker — **there is no way to mint a key per member of a repeated group.**
   `Manifest.node_keys(**values)` takes one flat dict with no iteration dimension, and
   `staticVars` are global to a materialization.

(3) is why `Encounter.participant` is capped at cardinality 1 (DR-201 §5.1) and why
`MedicationAdministration.dosage` will hit the same wall.

## 3. Proposed shape

New module, Agent 5's package:

```python
# src/fhir_sulo/identity/nodes.py

@dataclass(frozen=True)
class IterationKey:
    """The dimension that does not exist today."""
    group: str                 # "participant", "dosage"
    discriminator: str         # content-derived, NOT the ordinal -- see §5
    ordinal: int               # recorded for audit, never keyed on alone

@dataclass(frozen=True)
class NodeRequest:
    node_name: str             # "result", "patientRole", "person", ...
    strategy: str              # "template" | "entity" | "quality" | "unit"
    inputs: Mapping[str, str]  # obsId, versionId, canonicalUrl, ...
    iteration: Optional[IterationKey] = None

class NodeIdentityService:
    def __init__(self, policy: PolicyBundle,
                 identity: IdentityService,
                 terminology: TerminologyService) -> None: ...

    def mint(self, request: NodeRequest) -> NodeOutcome:        # Resolved | Rejected
        ...
    def mint_all(self, declarations, bindings, context) -> NodeSet:
        ...
    def describe(self, family: str) -> Mapping[str, str]:
        """The generated `node_key_rules` block -- see §4."""
```

`NodeOutcome` follows the existing house rule: a sealed union whose rejected arm has **no IRI
attribute** and whose `unwrap()` raises, so a caller cannot get a node IRI out of a failed mint
by accident. Same shape as `IdentityOutcome` and `CodeOutcome`.

What moves:

- `Manifest.node_keys()` is deleted. `manifest.node_key_declarations` returns the templates as
  **data**; `NodeIdentityService` executes them and enforces the scheme (allowed placeholders,
  required placeholders per repeated group, no two node kinds producing one IRI).
- `families.py`'s hand-written `values["person"] = …`, `values["quality"] = …`,
  `values["unitIri"] = …` become declarations. `families.py` keeps only genuinely
  family-specific knowledge: which element path, which LOINC code, which quality class.
- A new `policies/node-key-policy.v1.json` holds the scheme — allowed strategies, placeholder
  vocabulary, collision rules — versioned into `policy_version` like the other three tables.

What does **not** move: the manifests keep their templates. A map author must control the names
their map emits; those names are part of the map contract.

## 4. `MapContract.node_key_rules`: generated, then validated

Not deleted — reviewers read contracts, and R7 asks a human to sign off on example graphs, so a
human-readable statement of what each node IRI is belongs in the contract. Not hand-written
either, because that is how it became prose nobody checks.

Proposal: it becomes a **derived view**, exactly like `maps/r4/rehash.py` and
`fixtures/expected/build.py --check` already work in this repo.

- `NodeIdentityService.describe(family)` generates the block from the declarations plus the
  scheme.
- A contract test asserts the committed JSON **equals** the generated block, so it cannot drift.
- `MapContract.__post_init__` gains real validation: every key names a declared node, every
  value parses either as a template over known placeholders or as a `strategy:` reference.

This converts a block that currently reads as coverage into one that is coverage.

## 5. What this unblocks at Gate 5, and the one real risk

DR-201 §5.1 offers three options. **Option B becomes available**, with A as its implementation
detail:

1. the host skolemises each member of the repeated group;
2. `NodeIdentityService.mint(node="clinicianRole", iteration=IterationKey("participant", disc, i))`
   returns a distinct, deterministic IRI per member;
3. the runner builds **N single-member passes**, each rooted at that member's IRI with its own
   `staticVars`.

That sidesteps "staticVars are global to a materialization" — because there are N
materializations. The engine constraint is untouched. What changes is that *something owns the
per-iteration key*.

**The open risk, stated rather than glossed.** DR-302 records that a FHIR participant is a
blank node with no source IRI to root a pass at, so the member must be skolemised *before* it
can be minted, and that skolem must be deterministic and derived from source content. The
discriminator choice is a genuine decision with no obviously right answer:

- **ordinal** is unstable under reordering — and `bp-reordered-serialisation` exists precisely
  because this project does not assume serialisation order is meaningful;
- **content hash of the member** is stable under reordering but re-keys when any field in the
  member changes, so correcting a dose would move the dosage node. That may be right (it is a
  different dose) or wrong (it is the same dosage, corrected) — which is the same question R2
  asked about qualities, in a new place.

**This should be prototyped before the rest of the proposal is accepted**, on a two-participant
Encounter fixture. It is the only part whose feasibility I have not verified by reading
existing code.

## 6. Migration, and why it is safe to do in phases

Blast radius if any minted IRI moves: every golden graph under `fixtures/expected/`, plus
roughly fifteen test modules that name a minted IRI literally
(`test_validation_shapes.py:393`, `test_reasoning_pro.py:551`, `test_competency_queries.py:217`,
`test_lineage.py:38`, and so on), plus `benchmarks/generator.py`.

So **phase 1 must be value-preserving**: change who mints, not what is minted.

| phase | change | acceptance |
| --- | --- | --- |
| 0 | this proposal | lead's review |
| 1 | `NodeIdentityService` executes the existing templates; `families.py` declares; `Manifest.node_keys()` goes | `build.py --check` ok; fixture fingerprint byte-identical; full suite green |
| 2 | `node_key_rules` generated + validated; `MapContract` validation added | the committed block equals the generated one; editing it by hand fails |
| 3 | `IterationKey`, deterministic member skolemisation, N-pass runner | a **new** two-participant Encounter fixture; Gate 5 dosage |

Phases 1 and 2 are value-preserving and independently revertible. Phase 3 only affects node
kinds that cannot be produced at all today, so it cannot move an existing IRI.

The verification instrument already exists: the fingerprint harness built for IR-602 covers 38
person IRIs, 228 quality IRIs across both modes, 73 terminology decisions, 37 expected-graph
digests and both canonicalisers over all 82 fixture payloads, and reduces to one sha256. It
proved IR-602 byte-identical. It should gate phase 1 the same way.

## 7. Ownership, stated plainly

If this is accepted, a surface that is Agent 3's today becomes shared:

- **Agent 3 keeps** the node-key declarations in the map manifests. They are part of the map
  contract.
- **Agent 5 owns** the scheme, its execution, its validation, and the iteration dimension.

That is the smallest split that still lets one component answer "what is node *X*'s IRI for
input *Y*", which is what IR-603 actually asks for.

## 8. Three things found while surveying this, which are not part of the proposal

**(a) DR-005's decision was never applied.** DR-005 §1 records "**Decision: `scoped-slug`**",
with the rationale that `scoped-hash` gives expected graphs "not reviewable by a human, and the
reviewer has to check those graphs". The shipped policy is `scoped-hash`
(`policies/identity-policy.v1.json`), and every expected graph carries 32-hex IRIs —
`person-144658abc676816c09b76ed12e09956d`. No test asserts the live `key_style`, which is why
nobody noticed. Since the stated reason for the decision was R7 reviewability, and R7 is the
one item still blocking Gate 0, this is worth settling before the reviewer is asked again.
Flipping it is a one-line policy change plus a regeneration of the golden graphs — and it would
move every person IRI, so it should happen *before* any phase of this proposal, not during one.

**(b) The `Encounter.participant` loud-failure claim is asserted nowhere.** The contract says
"a second participant fails validation loudly (exit 1, parseable Failure) rather than being
silently dropped". There is no two-participant fixture anywhere under `fixtures/r4/encounter/`,
so nothing tests it. Worse, `families.py:136` hard-codes
`"Encounter.participant[0].individual"` while `profiles/fhir-r4-element-table.json` declares
`participant` as repeating — so if the ShEx cardinality cap were ever lifted without touching
that line, participant 2 would be **silently dropped**, which is exactly the outcome the
contract promises cannot happen. Phase 3 needs this fixture anyway.

**(c) `MockIdentityService` still duplicates contained scoping.** IR-604 moved the rule into
the identity service and the pipeline now delegates, but
`src/fhir_sulo/ingest/identity_port.py` keeps its own copy, which disagrees three ways: the
scope-key shape (`contained|{iri}|{target}`, keeping the `#`, vs the policy's
`{scope_id}|contained|{container_url}` with the `#` stripped), the digest length (16 vs 32 hex)
and the local-name prefix (`contained-`/`entity-` vs `person-`/`practitioner-`). It is a
different protocol in Agent 2's path, so I have not edited it. Either it should delegate to
`IdentityService`, or it should be deleted if `RefusingIdentityService` is the only ingest
default that matters.
