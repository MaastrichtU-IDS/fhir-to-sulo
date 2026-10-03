# DR-005 — Entity IRI style, and accepting Agent 5's out-of-scope writes

**Status:** Decided (Agent 1, integration lead)
**Date:** 2026-09-29
**Gate:** 1

## 1. Entity IRI style: ~~`scoped-slug`~~ → **`scoped-hash`** (reconsidered 2026-10-03)

> **This decision was recorded and never applied, then reconsidered when it was.**
>
> DR-005 decided `scoped-slug` on 2026-09-29. The policy shipped `scoped-hash` and stayed that
> way for four days, because **nothing compared the written decision to the running system** —
> the decision lived in this file and the behaviour in a JSON file. Found by Agent 5 during
> IR-602, not by a test.
>
> Applying it surfaced the reason it was wrong. `scoped-slug` produces
> `person-synthea-pilot-r4-p123-144658ab`, which **embeds the FHIR resource id in the semantic
> individual's IRI**. No `owl:sameAs` is asserted and the two IRIs are distinct, so it does not
> breach concept note §2 literally — but it *names the person after the record*, and a reader
> seeing `p123` in a person IRI will treat it as `Patient/p123`. That is the conflation §2
> exists to prevent. An existing test said so in its docstring, and that argument is better
> than the readability one below.
>
> The reviewer also signed off **R7** — "the FHIR resource and its interpretation are distinct
> individuals" — against the opaque form, and found it reviewable enough in practice.
>
> **Reverted to `scoped-hash` the same day.** The readability cost argued for below is real and
> is accepted as the lesser concern. The systemic fix is
> `tests/contracts/identity/test_key_style_matches_the_record.py`, which asserts the live style
> equals the recorded decision and does not care which one that is.

### The original 2026-09-29 reasoning, kept for the record

Agent 5's identity service offers three key styles. This is an engineering choice about
fixture readability, not a clinical one — the person IRI is a run binding (concept note §4),
so no map hard-codes it and the choice is reversible.

| Style | Example | Assessment |
| --- | --- | --- |
| `scoped-hash` (their default) | `ex:person-80bd1ab4a9c002e7006238a62425bc3b` | Safe, but an expected-graph fixture full of these is not reviewable by a human, and the reviewer has to check those graphs. |
| `legacy-concept-note` | `ex:person-p123` | Matches the concept note's schematic graphs exactly, but **rejects any reference from a second source scope**. That is a trap: it works throughout Gates 0–4 on single-scope synthetic data and then fails confusingly the first time a second source appears. |
| **`scoped-slug` (chosen)** | `ex:person-synthea-pilot-r4-p123-<8 hex>` | The source id stays legible, so a reviewer can read an expected graph; the scope stays in the key, so nothing merges across sources. |

**Decision: `scoped-slug`.** Reviewability matters because R7 asks a human to sign off on
example graphs, and it must not be bought by building in a cross-scope failure.

Consequence: the concept note's schematic graphs use `ex:person-p123`. Expected-graph fixtures
will differ from the note by construction. That is a presentation difference, not a semantic one,
and must be stated wherever a fixture is compared to the note.

## 2. Out-of-scope writes: accepted

Agent 5 wrote outside its assigned paths in three places and flagged all three rather than
letting them pass unnoticed. All are accepted:

- **`src/fhir_sulo/policy/`** — canonical keying, audit record, policy loader, report renderer.
  The alternative was duplicating canonicalisation across `identity/` and `terminology/`, which
  is exactly how two services drift on determinism. Single-source is correct. Ownership of this
  package transfers to Agent 5.
- **`tests/contracts/test_identity_terminology_contracts.py`** — had to sit at the
  `tests/contracts/` root to be discoverable. See §3; this file is load-bearing.
- **`requirements-dev.txt`** — pins `pytest==7.4.4`. Root-level is correct for a dev dependency file.

## 3. The CI discovery gap they caught (a real defect in my tooling)

`unittest discover` does not descend into non-package subdirectories, so every suite under
`tests/contracts/identity/` and `tests/contracts/terminology/` was invisible to CI. Verified:

```
$ PYTHONPATH=src python3 -m unittest discover -s tests/contracts -p 'test_*.py'
Ran 33 tests          # 15 interface + 18 fallback -- not the 122 service tests
$ PYTHONPATH=src .venv/bin/python -m pytest tests/contracts -q
137 passed
```

Worse, `gate-check.py`'s `check_mock_services` tested only that two *directories existed*, so the
Gate 1 condition "deterministic mock terminology/identity service available" would have passed
vacuously. Both fixed in this commit:

- `make contracts` now runs pytest as the authoritative runner, with the stdlib path as a
  fallback; `make contracts-stdlib` keeps the no-venv path green; CI runs both.
- `check_mock_services` now requires a determinism/replay test to exist **and** the suite to pass.

## 4. Independent verification of the determinism claim

Agent 5 reported a fault injection proving their replay test is not vacuous. Re-done
independently by the lead rather than accepted: a per-process salt was injected into
`policy/canonical.py::digest()`.

```
FAILED tests/contracts/test_identity_terminology_contracts.py::DeterminismContract::test_replay_across_separate_processes_is_byte_identical
FAILED tests/contracts/identity/test_determinism_replay.py::test_replay_across_separate_processes
2 failed, 135 passed
```

Caught by both the pytest suite and the stdlib CI-visible suite. Reverted; 137 pass. The
determinism guard is real and it is covered in CI.

## 5. Noted for Agent 6

Answering review item **R2** (quality identity) **changes every quality IRI**, because the two
modes key on different inputs. Person IRIs are unaffected (verified: seven unrelated policy edits
leave every person IRI byte-identical, because keying uses a sticky `key_revision` rather than
the table's semantic version). R2's answer is therefore a graph-key-affecting event and must be
handled as a migration, not a config change.
