# DR-007 — Integration record: merges, defects found, and open debt

**Status:** Decided / recorded (Agent 1, integration lead)
**Date:** 2026-09-29
**Gate:** 0 → 4

All five agent branches are merged into `integration/gate0-1`. Every agent's headline claim was
re-verified by the lead through fault injection rather than accepted on report.

## 1. Defects found *in the integration*, not in any one branch

These are the merge's own findings. None was visible from inside a single worktree.

| # | Defect | Consequence if unfixed |
| --- | --- | --- |
| 1 | `unittest discover` does not descend into non-package subdirectories | 122 of Agent 5's tests invisible to CI; `check_mock_services` passed on two directories existing |
| 2 | `TransformResult` lineage guard keyed on `self.lineage` | a `MAPPED` result with quads and **no** lineage validated and reported `is_loadable` — the exact case the guard existed to stop |
| 3 | Agent 4 and Agent 6 both wrote `tests/*/support.py`; `tests/` was not a package | six integration modules failed to collect; one `support` bound for both suites |
| 4 | `RunRecord` had no `renderer_id` (IR-601) | a renderer change was invisible to the graph key: reprocessing after one reported `unchanged` while triples could differ |
| 5 | Agent 5's determinism AST guard used `rglob` over all of `src/` | at integration its scope silently widened and it began flagging legitimate constructs — `RunRecord.activity_time` (which *must* be wall-clock) and the reasoner's temp-file uuids |
| 6 | `make clean` could not reach the bytecode cache | on this machine `sys.pycache_prefix` is `~/Library/Caches/com.apple.python`, i.e. **outside the tree**; a stale entry survived an edit and produced a module whose runtime behaviour contradicted its own source |
| 7 | Gate 2/3 map suites skipped in CI | the whole Gate 2/3 suite never ran on a clean runner; a skip is not a pass |

Fixes: (1) pytest is the authoritative runner, stdlib path kept green, both run in CI.
(2) keyed on `target_quads`; contract **0.2.0**. (3) `tests/` and `tests/integration/` are
packages, imports made relative. (4) `RunRecord.renderer_id` added and folded into the graph
key's content fields; contract **0.3.0**. (5) the guard is now two explicit tiers — a *declared*
key-path module list (no clocks, uuids, randomness) and an all-of-`src` ban on the builtin
`hash()` — plus a meta-test that the declared list names real files, so it cannot silently
shrink to nothing. (6) `make clean` resolves `sys.pycache_prefix` and clears it. (7) a Docker CI
job runs `engine-live`, `lint-schemas`, and the map and integration suites with
`FHIR_SULO_REQUIRE_ENGINE=1`.

## 2. Verification performed by the lead

Each was injected, observed to fail, and reverted.

| Claim | Injection | Result |
| --- | --- | --- |
| Agent 5 keying is deterministic | per-process salt into `policy/canonical.py::digest()` | 2 failures, incl. the CI-visible stdlib mirror |
| Agent 2 renderer preserves fidelity | decimal trailing-zero stripping | 3 failures on `FhirNumber('55.0') != FhirNumber('55')` |
| Agent 4's linter honours its exit contract | ran the negative pairs directly | exit 1 on errors, 0 on clean — checked because exit-0-on-failure is what got the engine CLI banned |
| The driver cannot catch nested repetition | read the live-engine test | confirmed: bindings all consumed, no unbound variables, panel count ≠ 2 |
| Agent 6's reasoner verification | ran HermiT and ELK through the same path | HermiT entails and refutes; ELK does neither, silently — the negative control is real |
| Agent 6's benchmark | re-ran `benchmarks/run.sh` from clean | 168.58 s, 1.44 GB vs targets of 15 min / 6 GB |
| Agent 3's BP multiset | swapped the systolic/diastolic LOINC codes **and rehashed**, so only semantics could catch it | 8 failures incl. `test_the_concept_note_multiset_is_exactly_right` |
| The canonicaliser drift guard | NFC → NFD in `store/canonical.py` | 3 failures |

One injection was a **no-op** and is recorded as such: loosening the diastolic constraint to also
accept the systolic code changed nothing, because the fixture data still forces the correct
assignment. It is evidence the design is robust, not evidence about the guard.

## 3. Decisions taken

- **Entity IRI style `scoped-slug`** (DR-005) — readable enough for a human to review an
  expected graph, without `legacy-concept-note`'s built-in cross-scope rejection.
- **`renderer_id` joins the graph key** (IR-601). Anything that can change an emitted triple
  belongs in the key; a renderer change must re-key rather than report `unchanged`.
- **`make gate1` requires Docker.** A gate that can pass without running the engine is not
  evidence. `make contracts-stdlib` remains the zero-dependency path.
- **`gate-check.py` enforces gate ordering** (plan §6 rule 5): a later gate reports `HELD`, never
  `PASSED`, while an earlier one is blocked.
- **pytest pinned to 8.3.5**, resolving the Agent 2 / Agent 5 add/add conflict; Agent 5's suite
  passes unchanged on it. `rdflib` resolved to 7.1.4 (dev) over 7.1.1 (runtime).
- **HL7 oracle vendored** (DR-006) with a CC0 provenance note, rather than making four
  conformance tests network-dependent.

## 4. Open debt, with owners

| Ref | Item | Owner | Blocking? |
| --- | --- | --- | --- |
| IR-602 | `policy/canonical.py` and `store/canonical.py` are independent implementations of the same rules. They **currently agree** — verified over a corpus exercising NFC folding, key ordering, nesting and float rejection, with a test that fails on drift (proved by an NFC→NFD injection). Converging them into one module is the right end state. | Agents 5 + 6 | no — drift now fails CI |
| IR-603 | **Node identity is owned by two components.** Agent 5's service mints person and quality IRIs; result, record, role, interval and time IRIs are minted from rules in Agent 3's map manifests. One component should own node identity. | to assign | no, but it will bite at Gate 5 |
| IR-604 | Contained-reference scoping (`#p-inline` must not merge across containers) is applied by Agent 3 and duplicated in Agent 2's mock. It belongs inside the identity service, not in every caller. | Agent 5 | no |
| CD-4 | Lineage reaches the binding tree, not the source triple. | Agent 6 | no — scoped, not glossed |
| DR-201 §5.1 | **`Encounter.participant` is capped at cardinality 1.** A second participant fails loudly. Not a repetition problem: each participant needs distinct minted role and holder IRIs, and `staticVars` are global to a materialization. DR-302's decomposition does not rescue it, because a FHIR participant is a blank node with no source IRI to root at. **This recurs for any repeated group whose members need distinct minted IRIs, including Gate 5's `MedicationAdministration.dosage`.** | Agent 3 + whoever scopes Gate 5 | not for Gates 0–4 |

## 5. Gate status at the close of integration

```
Gate 0 BLOCKED  (8 pass, 0 fail, 1 manual; own conditions BLOCKED)
Gate 1 HELD     (6 pass, 0 fail, 0 manual; own conditions PASS)
Gate 2 HELD     (5 pass, 0 fail, 0 manual; own conditions PASS)
Gate 3 HELD     (4 pass, 0 fail, 0 manual; own conditions PASS)
Gate 4 HELD     (5 pass, 0 fail, 0 manual; own conditions PASS)
```

Every gate's engineering conditions pass. **Gate 0's single remaining item is the human
reviewer's sign-off**, and by plan §6 rule 5 every later gate is correctly `HELD` behind it.
No gate is reported as passed, and nothing in `REVIEW-REQUEST.md` (12 items) is marked approved.
