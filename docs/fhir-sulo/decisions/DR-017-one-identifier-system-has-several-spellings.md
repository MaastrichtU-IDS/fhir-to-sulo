# DR-017 — One identifier system has several spellings, and the key must not care which arrived

**Status:** Found and fixed 2026-10-04 while verifying a URI I had written from memory
**Gate:** 0 (R8b) · follows [DR-015](DR-015-person-identifier-index.md)

## How this was found

DR-015 carried a caveat: BSN's canonical system URI had been written into this repo **from
memory** and should be confirmed against Nictiz. Confirming it found that the URI was right —
and that memory had missed something that matters more.

## BSN has two legitimate `Identifier.system` values

| spelling | where it comes from |
| --- | --- |
| `http://fhir.nl/fhir/NamingSystem/bsn` | the preferred form, FHIR-native systems |
| `urn:oid:2.16.840.1.113883.2.4.6.3` | anything derived from HL7 v2 or CDA |

Both are correct. Across **a variety of healthcare systems**, both will arrive — a FHIR-native
hospital and a v2-derived feed describing the same person will not spell the identifier the
same way.

US SSN has the same shape: `http://hl7.org/fhir/sid/us-ssn` and `urn:oid:2.16.840.1.113883.4.1`.

## Why exact-string matching was the wrong default

The system string is a **key input**. Left alone, the two spellings would have produced:

- at the allowlist: one spelling matched, the other not person-identifying, so **not indexed at
  all** — and an unindexed record does not fail, it quietly keys on its address;
- at the key: if both *were* allowlisted, two IRIs for one person, which is the exact opposite
  of what R8b exists to do.

Either way the two hospitals' records are never reunified and **nothing says so**. That is the
failure mode this whole area has been designed against, and it would have shipped.

## The fix

An allowlist entry may declare `equivalent_systems`. Every accepted spelling maps to the
entry's primary `system`, and that canonical form is what gets keyed — never the spelling that
happened to arrive.

The canonicalisation is applied in **both** places, because either alone is a silent miss:

- `IdentityService._person_identifier_canonical_map()` — for identifiers carried on a reference;
- `PersonIdentifierIndex.build()` — which now accepts the canonical map, so a record indexed
  from a v2-derived export lands under the same key as one from a FHIR-native export. The CLI
  hands it the map rather than a flat list. A plain iterable still works; aliasing is opt-in.

**An alias does not promote a system.** BSN and its OID both remain `proposed` and type nothing;
a test asserts that neither spelling reaches the canonical map in the shipped policy. Enabling
BSN is still a governance decision.

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
1006 passed

$ make verify-clean-clone
== clean clone verified ==
```

`test_the_uri_and_the_oid_form_are_one_person` promotes BSN in a test-local policy — the only
honest way to exercise an aliased system whose real status is `proposed` — and asserts a
FHIR-native record and a v2-derived record become one person.
`test_both_spellings_index_under_the_canonical_one` asserts the same at the index layer.

## What this suggests about the others

The synthetic pilot namespace has no alias because this project mints it. Every **real**
identifier system should be assumed to have at least a URI form and an OID form until checked.
Adding a system to the allowlist without checking its aliases is a way to produce an index that
looks populated and reunifies nobody.
