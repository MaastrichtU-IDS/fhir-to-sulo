# DR-006 — Integration decisions on Agent 2's open points

**Status:** Decided (Agent 1, integration lead)
**Date:** 2026-09-29
**Gate:** 0 → 1

## 1. Vendoring HL7 spec examples: accepted

`fixtures/r4/_oracle/` holds six HL7-published R4 example files (48 KB). Accepted, with a
provenance and licence note added (`fixtures/r4/_oracle/README.md`).

Reasoning: the alternative Agent 2 offered was making four conformance tests network-dependent,
which is worse on every axis that matters here — it makes CI flaky, makes the offline claim
false, and means the oracle can change under us without a commit. HL7 publishes FHIR
specification content under CC0 1.0, so there is no licence obstacle. The files are labelled
as an external oracle and marked do-not-edit, because an edited oracle is a tautology.

## 2. `SubjectContext` stays in `ingest/identity_port.py` for now

Agent 2 offered to move it into `contracts/`. Declining for the moment: the four contract types
are frozen and versioned (`CONTRACT_VERSION`), and promoting a fifth type belongs to a
deliberate contract revision, not a merge. It is used across exactly one boundary (ingestion →
identity) and both sides already agree on it. Revisit if Agent 3 or 6 needs it, at which point
it becomes a `CONTRACT_VERSION` bump.

## 3. Entity class on `establish()`: deferred to Agent 3's need

Agent 2 flagged that `establish()` might need to return an entity *class* (person vs
practitioner) which they do not need but Agent 3's §6 role typing might. This is downstream of
review item **R8** (is a Practitioner a person?), so the interface cannot be settled before the
reviewer answers. Agent 3 should code against the current signature and raise it if blocked.

## 4. Renderer choice: endorsed, and the evidence is strong

Agent 2 rejected `validator_cli.jar` on a hard blocker, verified at source rather than inferred:
`ValidationEngine.convert` selects `FhirFormat.JSON` or `FhirFormat.XML` by output extension and
never reaches `FhirFormat.TURTLE`, so asking for `.ttl` silently writes XML. Reaching Turtle
would mean writing and maintaining a Java shim around a 200 MB jar that still fetches
terminology over the network at run time.

The replacement — a stdlib-only Python renderer — is validated against HL7's own published
Turtle for the three examples the concept note cites, graph-isomorphically. That is external
validation, which is what the round-trip condition needed and what a self-written renderer
usually lacks.

Note this moots the JVM tension I raised with Agent 2: the question of whether ingestion counts
as "the mapping stack" for the acceptance matrix's no-JVM row never arises, because there is no
JVM anywhere in the pipeline.

**Independently verified by the lead**, not accepted on report. Injected decimal trailing-zero
stripping into `fhir_rdf.py` (the classic float round-trip fidelity loss):

```
FAILED tests/contracts/ingest/test_roundtrip.py::TestRoundTrip::test_committed_canonical_rdf_matches_the_pinned_renderer
FAILED tests/contracts/ingest/test_roundtrip.py::TestRoundTrip::test_every_fixture_source_round_trips_exactly
FAILED tests/contracts/ingest/test_roundtrip.py::TestPreservedFacets::test_the_three_time_elements_are_distinguishable
E   "$.valueQuantity.value: FhirNumber('55.0') != FhirNumber('55')"
3 failed, 247 passed
```

Reverted; 250 pass. The fidelity guard is real.

## 5. pytest version conflict resolved to 8.3.5

Agents 2 and 5 both added `requirements-dev.txt` (add/add conflict). Resolved to the union with
`pytest==8.3.5` (Agent 2's, the newer) and `rdflib==7.1.4`. Agent 5's 122 tests were written
against 7.4.4; verified they pass unchanged on 8.3.5 — the combined suite is 250 passing.
