# DR-601 — Deterministic graph key, and what a correction replaces

**Status:** Decided (Agent 6; engineering decision, explicitly delegated by REVIEW-REQUEST.md
"Items explicitly *not* on this list — graph key and correction mechanics")
**Date:** 2026-09-29
**Gate:** 4 (binds Gates 2 and 3, which must key their output the same way)
**Implements:** concept note §7 "the generated graph for one source resource/version has a
deterministic graph key"; plan Gate 4; acceptance rows Correction and Deployability.

## The decision in one line

**Two identifiers, not one:** a `graph_key` naming one immutable derived graph, and a
`subject_key` naming the replacement slot that all versions of one resource share.

## Why one identifier cannot work

Concept note §7 and plan Gate 4 ask for two things that a single key cannot satisfy at once:

- §7: *"the generated graph for one source resource/**version** has a deterministic graph key"* —
  so the version is in the key, and version 1 and version 2 have **different** keys.
- Gate 4: *"version 2 removes stale version-1 derived assertions from the current semantic
  graph while preserving version-1 lineage"* — so something must say that G2 **supersedes** G1
  rather than sitting beside it.

If the key omitted the version, loading version 2 would overwrite version 1 in place and its
lineage would be gone. If the key included the version and nothing else existed, G1 and G2 would
be two unrelated graphs and the stale assertions would never leave the current graph. Both
failures are silent. Hence:

| Identifier | Function of | One per | Used for |
| --- | --- | --- | --- |
| `graph_key` | every input that can change a triple | resource **version** (and map, policy, engine…) | naming, retrieving and auditing one derived graph |
| `subject_key` | source canonical URL + map id | resource **lineage** | the replacement slot: at most one *current* graph per slot |

The subject key is embedded in the graph key IRI, so it is recoverable without rehashing:

```
urn:fhir-sulo:g:<subject-24-hex>:<content-40-hex>
urn:fhir-sulo:s:<subject-24-hex>
```

## What the content key covers, and why

**Rule: exactly the inputs that can change an emitted triple, and nothing else.**

| Field | Why a change to it changes the triples |
| --- | --- |
| `source_canonical_url` | different resource |
| `source_version_id` | different version — concept note §7 names this explicitly |
| `source_json_digest` | guards a FHIR server that reuses a `versionId` after an edit; also lets "unchanged" be decided from the key without diffing graphs |
| `map_id`, `map_semantic_version`, `pairing_hash` | different schema pair, hence different triples |
| `sulo_version` | target upper-level vocabulary |
| `domain_ontology_version` | domain classes emitted (blocked on **R1**) |
| `terminology_snapshot` | the code-to-class rule changes emitted types |
| `policy_version` | the identity and quality-identity policy changes node IRIs (**R2** decides this outright) |
| `engine_build` | DR-301 B2/B3: two engine builds can silently emit different graphs, so an engine upgrade must mint a new key rather than overwrite in place |
| `contract_version` | the interface generation the run was produced under |

**Excluded:** `run_id`, `activity_time`, `output_digest`, `validation_report_digest`,
`transform_status`, `superseded_by`, `notes`. The first two are wall-clock; the rest are
*outcomes*. Keying on an outcome makes the key uncomputable before the run, which destroys the
main use of a deterministic key: asking "do I already have this graph?" without producing it.

### Consequences the reviewer and the other agents should know

- **An engine upgrade re-keys every graph.** That is intended. It is also visible: the store
  reports 10,000 `replaced` actions, not 10,000 `unchanged`, and the archive keeps the old
  graphs. The alternative — an engine change silently overwriting in place — is worse.
- **An open review item is recorded, not blanked.** `domain_ontology_version` is
  `"unresolved:R1"` today. An empty string is refused, because "we had not decided" and a real
  answer must not hash to the same graph. When R1 lands, every graph re-keys once, and that is
  the correct record of what changed.
- **What a correction replaces** is therefore: *everything derived from one source resource
  under one map*, regardless of which of the twelve inputs changed.

## Invariants, all enforced by tests

1. **Deterministic across processes.** `hashlib.sha256` only; never Python's `hash()`, which is
   salted per process. `test_graph_key.py` computes keys in three subprocesses with different
   `PYTHONHASHSEED` values and requires them equal; a separate test parses `store/` and
   `provenance/` with `ast` and fails on any call to builtin `hash`.
2. **Recomputable from the audit record.** `graph_key_from_run_record(rr) == rr.output_graph_key`.
   The store refuses to load anything that violates it. A key that could not be recomputed from
   its own record would make the correction history unverifiable after the fact — you could not
   tell an archived graph from a fabricated one.
3. **Every listed field is actually in the hash.** One test changes each of the twelve fields in
   turn and requires the key to change. A field in the spec but not in the hash would mean two
   different graphs sharing one key.
4. **Order-independent.** Sorted keys, NFC-normalised strings, ASCII-escaped JSON.
5. **A key collision with different triples is an error, not an overwrite.** If it ever fires, an
   input is missing from the key; the store says so and refuses.

## Correction semantics

| Event | Current graph | Archive | Source registry | Run ledger |
| --- | --- | --- | --- | --- |
| v1 loaded | G1 added | — | v1 registered | run 1 appended |
| v1 reprocessed, unchanged | **untouched** | — | unchanged | run 2 appended |
| v2 loaded | G1 → archive, G2 added | G1 marked `superseded` | v2 registered | run 3 appended; run 1 gets `superseded_by` |
| v2 → `entered-in-error` | G2 → archive | G2 marked `invalidated` with a reason | **v3 registered, nothing removed** | run 4 appended |

- **"Removed from the current semantic graph" is structural.** `current` and `archive` are two
  disjoint maps and retiring a graph *moves* it, so the guarantee does not depend on anyone
  remembering to apply a filter.
- **"Unchanged reprocessing changes no triples"** is exact: the current triple set, the store
  state digest and the per-graph objects are all identical, and the derived graph keeps its
  *original* generating run — a confirming run appends to the ledger and does not re-attribute
  the graph to itself. Provenance lives in separate named graphs (`urn:fhir-sulo:prov:*`) so the
  semantic layer can be compared triple-for-triple while the audit log grows.
- **Run records stay immutable.** `superseded_by` is recorded by storing
  `dataclasses.replace(old, superseded_by=…)`; the ledger checks that no other field differs and
  refuses a second, conflicting supersession.
- **The source record survives an error status**, because `SourceRecordRegistry` is append-only
  and nothing deletes from it (concept note §2).
- **A reused `versionId` with a different JSON digest is rejected**, not absorbed. A server that
  edits in place breaks version-based correction, and that is a fact to report.

## Namespace

`urn:fhir-sulo:` — a URN, deliberately. An `http(s)` graph IRI needs a project namespace, and
that is review item **R1**, which is open. A URN is a valid IRI for a named graph and commits
the pilot to nothing. Changing it is a `KEY_SPEC_VERSION` bump and a new decision record, because
it re-keys every graph.

## Open interface request to Agent 1 (IR-601)

`SourceContext.renderer_id` (Agent 2's FHIR RDF renderer) **can change the source graph and hence
the target triples**, but `RunRecord` has no field for it. Including it in the key anyway would
break invariant 2, since the key could no longer be recomputed from the run record — so it is
left out and raised here rather than quietly folded into another field.

**Proposal:** add `RunRecord.renderer_id` and append it to `CONTENT_FIELDS`. Until then, a
renderer change is invisible to the key, and reprocessing after one would report `unchanged`
while the triples may differ. This is a real, currently-unmitigated gap.

## Known duplication

`src/fhir_sulo/store/canonical.py` and Agent 5's `src/fhir_sulo/policy/canonical.py` implement
the same rules deliberately (sha256, sorted keys, NFC, ASCII, no floats). They are separate only
because the branches are independent and importing across them would couple two gates. **They
should converge on one module at integration.** The rules are identical today; if they drift,
entity keys and graph keys would normalise differently, which is exactly the class of bug both
modules exist to prevent.
