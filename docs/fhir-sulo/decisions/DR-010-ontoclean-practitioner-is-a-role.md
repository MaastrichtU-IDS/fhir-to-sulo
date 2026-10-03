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

## What does NOT change, and why

`resource_type` stays a key input, so `Patient/c7` and `Practitioner/c7` remain **two entities**.

That is not an OntoClean violation: `resource_type` here is a *provenance* discriminator —
which record this entity was derived from — not a claim about the entity's nature. Keeping two
records apart absent merge evidence is the conservatism of **R2b**, which records that no merge
rule exists and that `accepted_merge_evidence` is empty by design.

So after this change, one human recorded as both a Patient and a Practitioner is still two
person entities. That is a **known limitation under R2b**, not a rigidity error, and it should
be answered there rather than papered over here.

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
