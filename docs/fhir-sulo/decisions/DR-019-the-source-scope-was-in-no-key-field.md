# DR-019 — The source scope was in no key field, so two hospitals shared one replacement slot

**Status:** Found by adversarial review 2026-10-04; fixed
**Gate:** 0 · 4 (correction semantics) · bumps `KEY_SPEC_VERSION` to `graph-key/3`
**Follows:** [DR-016](DR-016-the-index-belongs-in-the-graph-key.md), which is the same defect
with the index in place of the scope, and [DR-018](DR-018-the-key-triple-came-from-string-surgery.md)

## The defect

`source_scope_id` is an **entity** key input — that is DR-014's whole point. It was in **no
graph key field at all**. Measured, for one Observation ingested under two scopes:

```
mumc-r4     canonical=https://fhir.example/Observation/1
radboud-r4  canonical=https://fhir.example/Observation/1

SAME canonical_url: True
SAME graph key    : True     ← one key, two graphs
SAME subject key  : True     ← one replacement slot
```

The entity IRIs *inside* those two graphs differ, because the scope keys entities. So one graph
key named two different graphs — exactly DR-016, which I had just fixed for the index without
noticing the same hole one field along.

The **subject key** is worse. It is the replacement slot, `(source resource, map)`. With two
hospitals sharing one slot, loading Radboud's `Observation/1` **supersedes** Maastricht's: a
correction that is not a correction, and one hospital's data silently replaced by another's.

In practice the store caught it — and misdiagnosed it, raising
`StoreIntegrityError: … a FHIR server that reuses a versionId after an edit`. Loud, wrong, and
it means multi-source loading fails on the first shared resource id.

The root cause of the identical canonical URL is separate and worth naming: `canonical_url` is
built from the **pinned manifest's** `server_base`, not from the source the resource came from.

## The fix

`source_scope_id` joins **both** field sets:

- `CONTENT_FIELDS` — because it changes the emitted entity IRIs, and a key that ignores what
  changes the content is not a key.
- `SUBJECT_FIELDS` — because which source a resource came from is part of *which resource it
  is*. Two hospitals' `Observation/1` are two resources and must occupy two slots.

`KEY_SPEC_VERSION` → **`graph-key/3`**, which that constant's docstring says is a decision
record, because a bump re-keys every graph in the store.

Adding it to `SUBJECT_FIELDS` does **not** disturb DR-016: the index is still absent from the
subject key, so enabling an index still supersedes within one slot rather than making a new one.

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
1040 passed
```

`TheSourceScopeIsAKeyInputToo` asserts two sources give two graph keys **and** two slots, that
one source twice still gives one slot (so ordinary supersession is intact), that the field is
in both sets, and that the key still recomputes from the run record alone.

## Still open

`canonical_url` still comes from the pinned manifest rather than the source, so two sources
produce the same URL for one resource id. The key no longer collides, but the recorded
canonical URL is wrong for every source that is not the pinned one. Fixing it means threading
a per-source `fhir_base_url` through ingest, which also moves `source_canonical_url` — a key
input — so it is a second re-keying and a separate decision.
