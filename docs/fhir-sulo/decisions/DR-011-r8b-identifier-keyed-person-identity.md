# DR-011 — R8b: a person-identifying business identifier keys the person

**Status:** Reviewer ruling 2026-10-03 (answers R8b); implemented, and **switched off pending
one further reviewer input** (the allowlist)
**Gate:** 0 (R8b) · Supersedes the deferral recorded in [DR-010](DR-010-ontoclean-practitioner-is-a-role.md)

## The ruling

R8a established that a practitioner is a person. R8b asked what happens when one human is
recorded as both a `Patient` and a `Practitioner`. The reviewer chose: **add a
shared-business-identifier merge rule.**

## Correcting the choice I offered

I presented this as "keep `resource_type` in the key, or drop it and merge". **The second
option was wrong and I should not have offered it.** FHIR logical ids are scoped per resource
type — the canonical address is `[base]/[type]/[id]` — so `Patient/c7` and `Practitioner/c7`
share the string `c7` by coincidence. Dropping `resource_type` would not implement a merge
rule; it would create a **collision**, fusing two people with no stated relationship.

So `resource_type` stays, for a reason unrelated to rigidity: it is part of the *address*. That
is a better defence of the behaviour than the "provenance" argument DR-010 originally made, and
unlike that one it survives scrutiny.

## Keying, not merging

A business identifier in an agreed namespace **is** an identity criterion for the person —
that is what `Identifier.system` means. So the person is keyed on it directly:

```
key_input_fields = (key_scheme, key_revision, entity_kind,
                    identifier_system, identifier_value)
```

One IRI, deterministically, with **no post-hoc graph rewriting, no `owl:sameAs` between
records, and no reasoning needed to collapse two nodes.** A Patient reference and a
Practitioner reference carrying the same national number arrive at the same IRI because they
are the same person, not because a merge pass fused them afterwards.

Deliberately **not source-scoped**: this is the recorded evidence that
`reference_scope.cross_source_merge` has always required. A national identifier is global by
construction; scoping it per source would defeat the only thing it is for.

## What the pipeline can actually see — a real limit

**The pipeline ingests one resource at a time.** It sees the `Observation` or `Encounter`, never
the `Patient` or `Practitioner` resource, and Bundles are out of scope
(`src/fhir_sulo/ingest/references.py`). So **`Patient.identifier` and `Practitioner.identifier`
are not available to it.**

**Correction, 2026-10-04.** This section originally claimed the rule "fires only on evidence
that exists today: `Reference.identifier` … and a contained resource's own identifiers."
**Both limbs were wrong, and the rule currently fires nowhere through the pipeline.**

- **`Reference.identifier`** is routed to the identity service by
  `pipeline/services.py`, but it never gets there: every shipped source schema requires
  `fhir:Reference.reference`, and a logical reference does not have one, so the resource fails
  **source validation** first. Verified —
  `test_r8b_cannot_fire_through_any_shipped_map` asserts the `SourceValidationFailure`.
- **Contained resources' own identifiers are never read.** `ingest/references.py` extracts an
  identifier only from `Reference.identifier`; resolving `#p-inline` to a contained resource
  does not look at that resource's `identifier` array at all.

So R8b is **implemented and unit-tested at the identity-service API, and unreachable through
all three shipped maps.** That gap is now pinned by a test rather than described in prose, so
closing it flips a test instead of going unnoticed.

Closing it means either widening three source contracts to accept a logical reference, or
ingesting Bundles so the `Patient`/`Practitioner` resources themselves are visible. Both are
scope decisions rather than fixes, and neither was taken on unprompted.

## The allowlist — restructured 2026-10-04

Entries, not bare URIs, so each carries a review status like every other table in this bundle.
Only `approved` and `pilot-provisional` key a person.

| system | status | scope |
| --- | --- | --- |
| `…/fhir2sulo/synthetic/person-number` | `pilot-provisional` | synthetic |
| `http://fhir.nl/fhir/NamingSystem/bsn` | `proposed` | real-world |
| `http://hl7.org/fhir/sid/us-ssn` | `proposed` | real-world |

A **synthetic** namespace is allowlisted so the mechanism is live and testable rather than
implemented-but-switched-off. It identifies nobody; no register issues it. **No real-world
namespace is interpretable**, and a test enforces exactly that rather than the weaker,
soon-obsolete "the list is empty".

Which `Identifier.system` URIs identify a *human* is a clinical and governance decision, not an
engineering one, so the implementation does not populate it. **While it is empty the mechanism
is fully implemented and tested but can never fire, and behaviour is identical to before R8b
was answered.**

A local MRN does **not** belong on it: an MRN identifies a patient record at one organisation,
not a human. A national person number or national provider number does.

## Rules added

| Rule | When | Then |
| --- | --- | --- |
| `ID-R12-identifier-keyed-person` | exactly one allowlisted identifier | resolved, keyed on it, not source-scoped |
| `ID-R13-multiple-person-identifiers` | two or more, discordant | rejected, `ambiguous-person-identifier` |
| `ID-R14-identifier-not-person-identifying` | identifier present, no address, none allowlisted | rejected, `identifier-not-person-identifying` |

**ID-R13 does not guess.** Picking the first would make identity depend on element order.
Reconciling several identifiers properly needs transitive entity resolution, which is stateful,
is not a keying rule, and is out of scope.

**ID-R14 exists for diagnosis.** Such a case already failed under ID-R6 `incomplete-key-inputs`,
which is true but says nothing useful. This names the reason and the remedy.

## Cost accepted, and it is not small

An entity keyed on an identifier has a **different IRI** from the same person keyed on a record
address — asserted by `test_the_identifier_key_is_not_the_record_address_key`. So if a record
later starts carrying an allowlisted identifier, **that person's IRI moves.**

That is a visible, deterministic re-keying event rather than silent drift, but it is real, and
it is why the allowlist is a reviewed list rather than "any identifier". Populating it is a
graph migration, not a configuration change.

## Contract change

`CONTRACT_VERSION` **0.3.0 → 0.4.0**. `ReferenceEvidence` gains optional `identifier_system`
and `identifier_value` on both the ingest and identity sides. Backward compatible: both default
to `None` and every existing path is unaffected.

Structured rather than parsed out of `raw_reference`: the identity service must not have to
read a display string to decide identity.

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
940 passed

$ PYTHONPATH=src .venv/bin/python tools/gate-check.py --all
Gates passing: 5 of 5
```

`tests/contracts/identity/test_r8b_identifier_keying.py` installs a **test-local** allowlist —
the only honest way to exercise a mechanism whose switch is a reviewer decision nobody has made
— and asserts: a Patient and a Practitioner sharing one identifier become one person; it merges
across source scopes; different values stay different people; the same value in a different
system is a different person; a non-allowlisted identifier does not key; discordant identifiers
are rejected rather than guessed; and the key is deterministic over 20 runs.

`tests/contracts/identity/test_distinctness.py` keeps the guard that previously asserted
`accepted_merge_evidence == []`. It is **not** relaxed: it now requires exactly one entry
carrying its reviewer attribution, plus a separate test that the allowlist is empty, which is
the live switch.

## Still open

Which identifier systems are person-identifying. Until that is answered the rule cannot fire.

---

## Addendum — 2026-10-04: exclusions, and why the rule rarely fires anyway

### Explicitly excluded, with reasons

- **`http://hl7.org/fhir/sid/us-npi`.** One system URI covers both Type 1 (individual provider)
  and Type 2 (organisation) NPIs. Allowlisting it would merge an **organisation** into a person
  entity whenever a Type 2 NPI appeared — a category error, not a near miss, because
  `entity_kind` here is `person`. It could only be admitted alongside a rule that first
  established the NPI is Type 1, which cannot be done from the identifier alone.
- **Any local MRN.** Identifies a *patient record at one organisation*, not a human. Two
  organisations reuse MRN values freely, and a practitioner has none, so it can neither merge
  correctly nor merge usefully.
- **Resource-level identifiers** such as `urn:ietf:rfc:3986` UUIDs. They identify the
  *resource*, not its subject. HL7's own BP example carries exactly this on
  `Observation.identifier`, which is the only `identifier` anywhere in this repo's corpus.

### Why this rule would rarely fire even once it is reachable

For R8b to merge anything, the Patient-side and Practitioner-side references must carry the
**same** `Identifier.system`. That is a stronger condition than it first appears: a patient
typically carries an MRN or a national **person** number, while a practitioner typically
carries a national **provider** number (NPI, BIG). Those are different namespaces and will
never match.

The rule fires only where one national **person** number is recorded on both — normal in the
Netherlands and the Nordics, unusual in the US. This is worth knowing before anyone treats R8b
as general-purpose patient/practitioner reconciliation. It is not; it is exact-match keying on
one agreed namespace.
