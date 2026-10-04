# DR-012 — R9: claim and enforce `vitalsigns`; fix the panel code; don't type it

**Status:** Reviewer rulings 2026-10-03 (answers R9a, R9b, R9c); all applied
**Gate:** 0 (R9) · 3 (BP target shape)

## The rulings

| Item | Question | Answer |
| --- | --- | --- |
| **R9a** | Which profile does the BP family claim? | **`vitalsigns`**, claimed *and enforced* |
| **R9b** | Does `85354-9` type the panel record node? | **No** — source-only |
| **R9c** | What is the parent `Observation.code`? | **`85354-9`** |

## R9c was a defect, settled by evidence rather than judgement

All five BP fixtures carried **`8480-6`** on the parent `Observation` — the *systolic* code,
identical to the code on their own systolic component. HL7's own published BP example
(`fixtures/r4/_oracle/observation-example-bloodpressure.json`), which this project's renderer is
already validated graph-isomorphically against, carries:

```
meta.profile : vitalsigns
category     : vital-signs
code         : 85354-9  "Blood pressure panel with all children optional"
value[x]     : (absent)
components   : 8480-6 systolic, 8462-4 diastolic
```

Fixing it was cheap because the design had anticipated it: the BP source shape already accepted
either parent code, `85354-9` was already in the code-interpretation table, and quality IRIs key
on the **component** codes — so **no quality IRI moved and no target graph changed.**

One thing did have to change: `85354-9` was not in the profile manifest's `pinned_codes`, so
eligibility rejected it. The wrong code had "worked" only because `8480-6` was pinned as a
*component* code. Pinned now, with a note that pinned means **recognised**, not **interpreted**.

## R9a: the claim was previously decoration

Before this change, `SourceContext.validated_profiles` was:

```python
validated = manifest_validated | (declared & known)
```

So a resource that merely **declared** `vitalsigns` was reported as validated with **nothing
checking it**. A test asserted exactly that, using an eGFR resource — and an eGFR is not a vital
sign. That test now asserts the opposite and is the clearest statement of what changed.

`validated_profiles` now means **checked and passed**. A profile with no `constraints` block in
the manifest cannot be validated and is never reported as validated; it is surfaced in `notes`
instead, so an unenforced claim is visible rather than silent.

### Scoped to what the resource declares, not to its type

`vitalsigns` applies to an Observation that **declares it in `meta.profile`** — which is what
`meta.profile` means in FHIR — not to every Observation. eGFR is not a vital sign, and forcing
`category = vital-signs` on it would be wrong. The manifest's `pinned_profiles` has no family
dimension, so declaration is both the correct and the available discriminator.

### What is enforced, and what is deliberately not

Five constraints, declared as **data** in `profiles/fhir-r4-pilot.json` so what is enforced sits
beside what is claimed:

| id | constraint |
| --- | --- |
| `vs-cat` | `category` includes `observation-category#vital-signs` |
| `vs-code-loinc` | `code` carries a LOINC coding |
| `vs-subject` | `subject` present |
| `vs-effective` | `effectiveDateTime` or `effectivePeriod` present |
| `vs-2` | with no `component`/`hasMember`, a `value[x]` or `dataAbsentReason` is required |

**Not enforced, and therefore not claimed:** the full vital-signs code value-set binding (only
LOINC-ness is checked), the UCUM unit binding on `value[x]`, and component slicing. Claiming a
constraint the pipeline does not check is the failure this list exists to prevent.

An unknown constraint *kind* raises rather than passing — a declared constraint nobody
implements is the same defect in a different place.

`bp` stays `candidate`. The corrected fixtures would in fact satisfy it, but claiming it would
assert more than HL7's own published example does.

## R9b: the panel code types nothing

`CODE-LOINC-85354-9` stays `proposed` with `result_class: null`. The panel record remains
`ex:ObservationRecord`; the code is retained in the source layer. Concept note §2: a code
literal alone is not an OWL class assertion. The panel's meaning is already carried
*structurally* — it `refersTo` both component results — so typing it would add nothing the graph
does not say.

`Observation.category` is likewise **required to be present and forbidden to be interpreted**,
and is declared `source_only` with that note. Profile conformance is FHIR validation, which the
plan keeps in the **host**; the ShEx source shape tolerates `category` with a wildcard and no Map
variable, so it cannot reach the target graph.

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
942 passed

$ PYTHONPATH=src .venv/bin/python tools/gate-check.py --all
Gates passing: 5 of 5

$ PYTHONPATH=src .venv/bin/python fixtures/r4/build.py --check
OK: 24 fixture cases match the pinned renderer
$ PYTHONPATH=src .venv/bin/python fixtures/expected/build.py --check
ok
```

**The expected target graphs did not change** — `git diff fixtures/expected/` is empty. That is
the check that R9b was actually honoured: a panel code that typed something, or a category that
leaked, would have shown up there.

`test_each_enforced_constraint_can_actually_fail` breaks each of the five in turn and requires
the matching constraint id in the error. A constraint nobody can break is a constraint nobody is
checking.

## A mistake worth recording

While rewriting the fixtures I truncated `fixtures/r4/bp/bp-two-panels/bp-2.json` to zero bytes:
the script passed `open(path, "w")` directly as an argument, so the file was truncated before
serialisation could fail. Restored from git and redone, rendering the JSON to a string **before**
opening the file for writing. The 0-byte file was caught because the next `json.load` raised —
but a silently emptied fixture that still parsed would not have been.
