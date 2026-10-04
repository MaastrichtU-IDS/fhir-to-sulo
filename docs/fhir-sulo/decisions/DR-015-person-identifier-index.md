# DR-015 — Reunifying one human across healthcare systems, on a BSN-like identifier

**Status:** Reviewer ruling 2026-10-04; implemented
**Gate:** 0 (R8b) · builds on [DR-011](DR-011-r8b-identifier-keyed-person-identity.md)
and [DR-014](DR-014-the-source-scope-was-a-module-constant.md)

## The ruling

> **Q.** Are five records of one patient meant to become one person in the graph, or five
> people who happen to be the same human in the world?
>
> **A.** "i do, if there bsn like attributes to uniquely identify"

So reunification is **conditional**: one person where a person-level identifier says so, and
separate people otherwise. Staying separate is not a failure mode — it is **R2b**, and it is
what must happen when nothing says two records are about one human.

## What blocked it

A BSN-style number lives on **`Patient.identifier`** — on the *Patient resource*. This pipeline
ingests one `Observation` or `Encounter` at a time and supports no other resource type, so the
identifier it needs is never in front of it. An Observation referencing `Patient/123` carries no
BSN, and DR-011's hope that `Reference.identifier` would supply one was wrong twice over:
source schemas reject logical references, and contained resources' identifiers are never read.

## The index, and why it is an input

`PersonIdentifierIndex` maps `(source_scope_id, resource_type, resource_id) → (system, value)`.
A pass over `Patient`/`Practitioner` resources builds it; the identity service consults it when
a reference carries no identifier of its own.

It is deliberately an **input**, not a lookup the service performs:

- `resolve()` stays a pure function of **(request, policy, index)**, so a replay with the same
  three reproduces the same IRIs — which DR-401 requires and which a service that went and read
  resources could not promise.
- The index carries a **digest**. Two indexes produce different entity IRIs for the same input,
  and a run record must be able to say which one it used. That is auditable rather than
  mysterious.
- Building it can read Patient resources from a Bundle, a directory or an export, and none of
  that reaches the identity service.

**Empty by default.** Nothing reunifies until an index is supplied, so the conservative outcome
is the one you get by doing nothing.

### What it refuses

- **Only person-typed resources** (`Patient`, `Practitioner`, `RelatedPerson`) are indexed. An
  `Observation.identifier` describes the observation, not its subject — HL7's own BP example
  carries a UUID there.
- **Only allowlisted systems.** A local MRN is not indexed at all, so it cannot reunify anyone:
  it identifies a record at one organisation, not a human.
- **Two discordant identifiers on one record** raise `PersonIdentifierConflict` rather than
  picking one, which would make identity depend on element order.
- **Two indexes disagreeing** about one record raise on merge. Scope is part of the key, so two
  systems cannot silently overwrite each other.

## What it looks like

```
index: maastricht-umc/Patient/123 -> synthetic-person-number|900001
       radboud-umc/Patient/987    -> synthetic-person-number|900001

MUMC  Patient/123 -> person-39e69ed5…   ID-R12-identifier-keyed-person
RAD   Patient/987 -> person-39e69ed5…   ID-R12-identifier-keyed-person
```

Different system, different record id, **one person** — on the identifier alone. Without the
index the same two inputs give two people, which is the behaviour this repo shipped yesterday
and still the behaviour when no identifier is present.

Partial coverage is safe: a record absent from the index keys on its address under
`ID-R1-single-candidate`, so indexing some patients does not disturb the rest.

## Addendum — 2026-10-04: sources, and seeing the migration first

Two of the three open points are now closed.

### Where the index comes from

`from_bundle`, `from_directory`, `save` and `load`, plus an operator CLI:

```
python -m fhir_sulo.identity.cli build \
    --source maastricht-umc=/data/mumc \
    --source radboud-umc=/data/radboud --out person-index.json
```

A directory is walked **sorted**, so the digest does not depend on filesystem order, and
Bundles and bare resources are both accepted. The allowlist comes from the policy, so the index
cannot drift from the reviewed decision — a `proposed` system is not indexed.

Three refusals, each because the failure would otherwise be silent:

- **A file that will not parse raises** rather than being skipped. An under-populated index does
  not fail; it just stops reunifying people, invisibly.
- **An index that merges nobody is refused** unless `--allow-empty`. That result usually means
  the allowlist is wrong, not that the data has no identifiers.
- **`load()` verifies the digest.** An index decides which records are one person, so an
  untracked edit silently re-keys entities.

### Seeing the migration before causing it

```
$ python -m fhir_sulo.identity.cli plan --index person-index.json
3 record(s) examined; 3 entity IRI(s) move; 2 record(s) collapse into 1 person(s).

Records that would become ONE person -- each line below is a claim that two records
describe one human, and is the part to review:

  .../person-39e69ed5...
    maastricht-umc           Patient/123
    radboud-umc              Patient/987
```

`plan_rekey` resolves every indexed record twice, with and without the index, under one policy —
so the diff is attributable to the index and nothing else.

Note that **3 move but only 2 collapse**. A record indexed under its own, unshared identifier
keys on that identifier rather than on its address, so its IRI changes even though it reunifies
with nobody. Worth knowing before reading a migration plan: *moved* and *merged* are different
counts, and only the second is a clinical claim.

## Still to decide

**Which real-world systems.** Only a synthetic namespace is allowlisted; BSN and US SSN sit at
`proposed`. Enabling BSN is a governance decision as much as an ontological one, and its
canonical system URI should be confirmed against Nictiz rather than taken from this repo — it
was written here from memory.

Nothing migrates existing graphs. `plan` says what would change; applying it is a separate,
unwritten step.

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
978 passed

$ PYTHONPATH=src .venv/bin/python tools/gate-check.py --all
Gates passing: 5 of 5
```

`tests/contracts/identity/test_person_index_reunification.py` covers both halves of the
conditional: two systems with one BSN give one person, a Patient and a Practitioner sharing one
give one person — and an empty index, a local MRN, and an unindexed record each leave the
records separate.
