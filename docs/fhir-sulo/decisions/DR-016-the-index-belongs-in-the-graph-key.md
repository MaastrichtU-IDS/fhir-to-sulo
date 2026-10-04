# DR-016 — The person index belongs in the graph key, and the migration is supersession

**Status:** Defect found and fixed 2026-10-04
**Gate:** 0 · 4 (correction semantics) · bumps `KEY_SPEC_VERSION` and `CONTRACT_VERSION`
**Follows:** [DR-015](DR-015-person-identifier-index.md), [DR-601](DR-601-graph-key-and-correction-semantics.md)

## The question that found it

DR-015 left "applying a migration" open, and I offered to design a migrator. Checking what one
would have to do found that the thing a migrator would be working around is a **defect**, and
that fixing the defect removes the need for the migrator.

## The defect

The store's graph key is a function of thirteen inputs (DR-601). The person-identifier index
was **not** one of them — but it decides which source records are one person, so it changes the
entity IRIs in the emitted graph.

```
graph key, index A: …32ba3afeecd7a136c8c0520b
graph key, index B: …32ba3afeecd7a136c8c0520b   ← the same
```

Two graphs with **different content** under **one key**. For a content-addressed store that is
the one intolerable failure: it would either believe it already held the graph and never
regenerate, or overwrite one with the other and keep no lineage between them. Enabling an index
would have corrupted the store quietly rather than migrating it.

## The fix

`person_index_digest` joins `CONTENT_FIELDS`, and `KEY_SPEC_VERSION` goes `graph-key/1` →
`graph-key/2` — which the spec's own docstring says is a decision record, because a bump re-keys
every graph in the store.

`"none"` is the explicit no-index token. `GraphKeyInputs` already refuses an empty string, on
the stated grounds that *"'we had not decided yet' is itself a fact about the run"* and must not
hash like a decision. The same rule applies here: **no index** and **some index** must not
collide.

`CONTRACT_VERSION` **0.5.0 → 0.6.0**: `RunRecord` carries the digest, because the key must stay
recomputable from the archived record alone.

## The migration is supersession, not a new tool

The **subject key** — the replacement slot, `(source resource, map)` — does **not** include the
index. So enabling one gives a graph a new *content* key inside the *same* slot:

```python
subject_key(before) == subject_key(after)    # same slot
before.graph_key    != after.graph_key       # different graph
```

That is precisely the shape of a `v1 → v2` correction, which the store already handles: the new
graph supersedes the old, the old stays retrievable, and the `prov` revision edge is emitted by
machinery that exists and is tested at Gate 4.

**So the migration is: enable the index and re-run.** No bespoke migrator, no graph rewriting,
no separate lineage scheme. That is a better answer than the one I offered, and it was only
available because the graph key is a pure function of declared inputs.

## What this does not do

It does not migrate anything by itself. Re-running is still an operator action, and
`python -m fhir_sulo.identity.cli plan` remains the way to see the effect first. What changed is
that re-running now *works* — before, the store would have refused to notice.

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
1003 passed

$ PYTHONPATH=src .venv/bin/python tools/gate-check.py --all
Gates passing: 5 of 5
```

`tests/integration/test_index_is_in_the_graph_key.py` asserts: two indexes give two keys; no
index is an explicit token and does not hash like an index; an empty digest is refused; the key
spec was bumped; the subject key is unchanged so supersession applies; and the key still
recomputes from the run record alone.

One test was updated rather than derived. `test_a_mapped_entry_carries_quads_and_provenance`
spells out the graph key's input names as a literal list. It would have been easy to derive it
from `CONTENT_FIELDS` and make it pass forever — but the point of that list is to notice when
the key's inputs change, and a derived one would notice nothing.
