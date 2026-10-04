# DR-020 — The last three review findings: contained fusion, alias shadowing, and a canonical URL that named the wrong server

**Status:** Found by adversarial review 2026-10-04; all three fixed
**Gate:** 0 (identity) · closes the review opened in
[DR-018](DR-018-the-key-triple-came-from-string-surgery.md) and
[DR-019](DR-019-the-source-scope-was-in-no-key-field.md)

## 1. A contained resource fused with a top-level patient

The person-index lookup used the **raw** dataset scope and the **raw** resource id, not the
effective container-scoped key the service applies everywhere else. Measured before the fix,
with an index holding a top-level `Patient/p-inline`:

```
top-level Patient/p-inline : person-39e69ed5…   ID-R12-identifier-keyed-person
contained  #p-inline       : person-39e69ed5…   ID-R12-identifier-keyed-person
FUSED: True
```

Two different people, one IRI, **on a coincidence of ids** — nothing about the contained
resource said it was that person. The policy already states the principle that makes this
wrong: *a contained resource has no existence outside the resource that contains it*, which is
why `ID-R8` scopes it to its container in the first place.

Contained candidates are now skipped by the index entirely. They key under `ID-R8` as before.
A contained resource's *own* identifiers remain a separate, unimplemented path — the pipeline
does not read them at all (DR-011's correction).

## 2. Alias shadowing was order-dependent

`equivalent_systems` (DR-017) resolves by walking the entries in order. If entry **B** listed
entry **A**'s primary system among its aliases, then A's canonical form depended on which entry
came first. Deterministic for a given policy file, and silently wrong: it merges two identifier
namespaces into one person.

`PolicyBundle.validate()` now refuses it — every accepted spelling must canonicalise to exactly
one system. An entry harmlessly repeating its own primary is still allowed; only a genuine
claim by two entries is an error.

This is validation of the kind the bundle already does for key style, hash algorithm and key
revision: the policy must not be able to contradict itself.

## 3. The canonical URL named the pinned server, not the source

```python
canonical_url = m.server_base + rtype + "/" + resource["id"]
```

`m` is the **pinned manifest**. So every source produced
`https://fhir.example/Observation/1` for its own `Observation/1`, regardless of where the
resource actually came from — and `source_canonical_url` is both a graph key input and half the
replacement slot.

DR-019 stopped the resulting collision by putting `source_scope_id` in the key. That was the
safety fix; this is the correctness one. The two sit together: the key no longer collides
*and* the recorded URL is now the resource's real address.

`ingest_*` take `fhir_base_url`, `Pipeline` carries it, and the CLI gains `--fhir-base` on
both `map` and `batch`. **The default is the pinned base, so nothing in this repo re-keyed.**

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
1054 passed
```

Each fix is pinned behaviourally: a contained resource no longer fuses and still keys under
`ID-R8` while a top-level record still keys on its identifier; one entry claiming another's
system is refused while repeating its own is allowed; two sources give two canonical URLs
while the default is unchanged.

## What this closes, and what it does not

Every finding from the 2026-10-04 adversarial review is now either fixed or recorded. Nothing
from it remains open.

It does **not** mean the identity path is proven correct. Three of these findings were false
merges reachable on ordinary input, and they were found by someone reading the code adversarially
rather than by 1,000 passing tests. The tests added since are behavioural rather than
source-text assertions, which is better, but the lesson is about the method: for this part of
the system, review found what the suite could not.
