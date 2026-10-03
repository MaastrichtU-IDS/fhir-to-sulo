# DR-010 — OntoClean: "practitioner" is anti-rigid, so it cannot be an entity kind

**Status:** Reviewer ruling 2026-10-03 (answers R8a); consequences derived
**Gate:** 0 (R8)

## The ruling

> we need to follow ontoclean semantics here and distinguish between rigid and antirigid
> properties. the term "practitioner" refers to a role. we should mint a PractitionerRole, and
> link an individual person to an instance of that role in the process in which they are active

## Why this is a defect and not a naming preference

OntoClean: a **rigid** property holds necessarily of its instances — if *x* is a person, *x* is
necessarily a person. An **anti-rigid** property holds contingently — *x* is a practitioner only
while practising, and can cease to be one without ceasing to exist.

The rule that bites here: **identity criteria must come from rigid properties.** An anti-rigid
property cannot supply identity, because the entity would change identity when the property
lapses.

`src/fhir_sulo/pipeline/services.py:117`:

```python
kind = "person" if expected_type == "Patient" else "practitioner"
```

`entity_kind` is one of the six `key_input_fields` for an entity IRI. So **"practitioner" is
currently an identity criterion.** The same human's IRI depends on the role they play. That is
the error OntoClean names, not a cosmetic one.

## The patient side already does this correctly

The asymmetry is the clearest evidence:

| | entity kind | entity IRI | role |
| --- | --- | --- | --- |
| patient | `person` | `person-…` | `ex:PatientRole` ✓ |
| practitioner | **`practitioner`** | **`practitioner-…`** | `ex:ClinicianRole` |

"Patient" is just as anti-rigid as "practitioner", and the patient side already pushes it into a
role and keeps the entity a person. The practitioner side does not. One pattern, applied
inconsistently.

## What changes

1. **`entity_kind` becomes `person` for both.** Identity is grounded in the rigid type.
2. **The IRI segment becomes `person-` for both.** It follows from the kind.
3. **Mint `ex:PractitionerRole`** in the R1 domain vocabulary, replacing `ex:ClinicianRole` for
   the Encounter participant.
4. The link shape is **unchanged** — it was already right:
   `person hasFeature role`, `role isFeatureOf person`, `encounter hasParticipant role`.
   The role is already scoped to the encounter (`clinician-role-enc-9`), which is what
   "in the process in which they are active" requires.

## Why `PractitionerRole` rather than keeping `ClinicianRole`

Both are roles, so neither is an OntoClean error; this is about which the source supports.
`Encounter.participant.individual` references a **`Practitioner`**, so `PractitionerRole` is
derived from what the record says. `ClinicianRole` names a clinical function the source did not
state — a small inference we do not need to make, and §2 asks us not to.

It also leaves **R12** clean: if a reviewed participation-type table is added later, `PPRF`
could refine `PractitionerRole` into something more specific, rather than contradicting a
function we had already asserted.

## What does NOT change — stated accurately

**This section originally overstated the fix.** It argued that `resource_type` remaining a key
input "is not an OntoClean violation" because it is a provenance discriminator. Independent
review showed that argument does not hold, and the correction matters more than the original
claim.

### The partition is bit-identical to the pre-change partition

`entity_for_reference` has exactly four call sites
(`src/fhir_sulo/pipeline/families.py:82,112,165,176`), each passing a single literal
`expected_type`, and `ID-R5-unexpected-type` rejects any candidate whose `resource_type` differs
from it. So for every request that resolved, the old `entity_kind` was a **deterministic
function of `resource_type`** — a field already in `key_input_fields`.

Removing a key field that is a function of another key field cannot change the equivalence
relation the key induces. Measured against the live service:

```
Patient/c7      -> person-39be962c396ba29c0b64640d1e5b11df
Practitioner/c7 -> person-afd67e8e52bcff0eda45d940c797e4e2
```

Every hash moved. Not one equivalence class did.

Secondary: `entity_kind_segments` now has exactly one key, so `entity_kind` contributes **zero
discrimination** while remaining in `key_input_fields` — an identity criterion that is a
constant.

### So what did this change actually achieve?

Three things, none of them nothing:

1. `EntityIdentity.entity_kind` was a first-class **assertion** that this individual *is a
   practitioner*. That assertion is gone.
2. The IRI named the person after an anti-rigid property. That label is gone.
3. An undeclared kind is now **rejected** rather than slugified, so the path that let this
   happen is closed.

What it did **not** achieve: `resource_type` is in `key_input_fields`, so it *is* an identity
criterion, and its values in this pipeline are exactly `{Patient, Practitioner}` — the same
anti-rigid pair under a provenance-sounding name. Calling it provenance does not change what it
does to the key.

### The honest statement

> The anti-rigid distinction was removed from the entity's **asserted kind** and from its
> **IRI label**. It is retained, unchanged, in the **key**, through `resource_type`.

**R8b is therefore not a downstream refinement of this ruling — it is the remainder of the
original finding.** It is routed to the reviewer, explicitly, rather than closed here. One
human recorded as both a Patient and a Practitioner is still two person entities, and no merge
rule has been reviewed (R2b, `accepted_merge_evidence` empty by design).

Pinned by `tests/contracts/identity/test_ontoclean_rigidity.py::ResourceTypeStillPartitionsPeople`,
which asserts the current behaviour *and* records that it is the unresolved remainder, so a
future ruling on R8b changes a test that says why rather than silently re-keying the graph.

## Expected blast radius

Every practitioner IRI moves -- in enc-baseline, `practitioner-75edba7e593927916da32e42c043e881` becomes `person-afd67e8e52bcff0eda45d940c797e4e2` -- because `entity_kind` is
a key input and its value changes. Person IRIs for patients are unaffected. Encounter goldens
regenerate; `ex:ClinicianRole` disappears from the emitted graphs in favour of
`ex:PractitionerRole`.

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
921 passed

$ PYTHONPATH=src .venv/bin/python tools/gate-check.py --all
Gates passing: 5 of 5

$ .venv/bin/python maps/r4/rehash.py --check            # ok
$ PYTHONPATH=src .venv/bin/python fixtures/expected/build.py --check   # ok
```

The expected graphs were **regenerated** by `fixtures/expected/build.py`, not hand-edited; the
two that changed are the two Encounter fixtures.

New guard: `tests/contracts/identity/test_ontoclean_rigidity.py` (9 tests) asserts that no
anti-rigid term is a declared entity kind, that each of
`practitioner, patient, clinician, subject, performer, author` is **rejected** as an entity kind
rather than slugified, and that a Practitioner reference mints a `person-` IRI carrying no
anti-rigid term.

Two further gaps found while applying this and closed:

- `tests/contracts/identity/test_key_style_matches_the_record.py` matched entity IRIs with a
  hardcoded `(person|practitioner|quality)`. Once `practitioner` stopped being an entity
  prefix, that alternative silently began matching the **role** node
  `practitioner-role-enc-9`. The pattern is now derived from the policy.
- The SHACL shortcut-predicate constraint listed `hasClinician`, but only `hasPatient` had a
  negative fixture, so dropping the other branches would have failed no test. Fixtures for
  `hasClinician` and `hasPractitioner` were added, and fault-injecting the `hasPractitioner`
  branch out of the constraint was confirmed to fail exactly one test.

## Independent review of this change, and what it found

An independent agent reviewed the applied change adversarially. It found four issues; all are
fixed. Two were defects I introduced *while applying the ruling*, which is worth recording.

**1 (high) — a prohibition silently shrank from four predicates to three.**
`tests/contracts/maps/test_map_contracts.py` banned
`("hasPatient", "hasSubject", "hasPractitioner", "hasClinician")`. The blanket
`clinician → practitioner` rename turned the fourth element into a **second copy of the third**,
so `hasClinician` stopped being forbidden in any target schema. A duplicated `subTest` still
passes, so nothing failed. This is precisely the "test weakened by a rename into vacuity" the
mandate forbids, and I did it. The list is now **derived from the SHACL constraint in
`base.ttl`** at test time, so the schema test and the shape cannot disagree about what is
banned, and it asserts at least four are found.

**2 (high) — the SHACL shortcut constraint was almost entirely untested.**
Only `hasPatient` had a negative fixture; `hasSubject` and `hasClinician` never did, and the
change added a fourth untested disjunct in `hasPractitioner`. Fixtures now exist for all four.
Each disjunct was neutralised in turn and confirmed to fail **exactly its own test**:

```
neutralised hasPatient      -> test_a_hasPatient_shortcut_is_caught
neutralised hasSubject      -> test_a_hasSubject_shortcut_is_caught
neutralised hasClinician    -> test_a_hasClinician_shortcut_is_caught
neutralised hasPractitioner -> test_a_hasPractitioner_shortcut_is_caught
```

A first attempt at this injection reported "0 tests failed" for `hasPatient`. That was wrong:
the edit had not applied, because `hasPatient` is the first disjunct and carries no leading
`||`. Nothing was perturbed, so nothing was demonstrated. Recorded because an unapplied
injection that reports a clean result is the most misleading outcome available.

**3 (medium) — the file a reviewer reads to check node keys still claimed to quote the concept
note "exactly".** An earlier attempt to fix this searched a `notes` key; the key is
`node_key_note`, so the edit silently did nothing and I did not verify it. Fixed, and the one
divergence is named.

**4 (medium) — the rename put an anti-rigid term back onto a person.**
`tests/integration/graphs/encounter-pro.ttl` had `ex:clinician-c7`, a node typed `ex:Person`.
The blanket rename made it `ex:practitioner-c7` — a *person* individual named after the very
anti-rigid property this ruling exists to keep off people, while its patient counterpart was
`ex:person-p123` throughout. The same asymmetry the ruling was about, reintroduced while fixing
it. Now `ex:person-c7`; `benchmarks/generator.py` had the same bug and is fixed.

Generalised into `NoPersonIsNamedAfterARole`, which scans every integration graph and every
expected target graph for a node typed `ex:Person` whose local name carries an anti-rigid term.
Restoring `ex:practitioner-c7` was confirmed to fail it.

### What this says about the method

A blanket textual rename is not a safe way to apply a semantic ruling. Both defects came from
the same cause: a term that is correct in one position (the role) and forbidden in another (the
person, and the banned-predicate list) cannot be rewritten uniformly. The guards added here are
positional, which is what the ruling actually requires.
