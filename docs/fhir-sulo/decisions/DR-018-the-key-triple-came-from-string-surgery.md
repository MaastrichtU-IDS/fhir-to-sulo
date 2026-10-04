# DR-018 — Three false merges: the key triple came from string surgery, and the fix missed the operator path

**Status:** Found by adversarial review 2026-10-04; all three fixed
**Gate:** 0 (identity) · affects every entity IRI a real deployment would mint
**Follows:** [DR-014](DR-014-the-source-scope-was-a-module-constant.md), which fixed one case of this and stopped short

## What review found

Three paths, all reachable through the shipped pipeline, all **silent** — status `mapped`, no
note, no diagnostic.

### 1. A versioned reference was attributed to the wrong patient

```python
resource_id = ev.resolved_target.rsplit("/", 1)[-1]
```

`Patient/123/_history/2` → `resource_id = "2"`. Measured before the fix:

```
Patient/123/_history/2  ->  person-be0d56cd…   ← the same IRI
Patient/2               ->  person-be0d56cd…   ←
Patient/123             ->  person-c001e688…
```

Not merely a merge. **A reference to patient 123 was attributed to patient 2.** Any FHIR server
that emits versioned references would have produced this on ordinary input.

`references.py` had parsed the type, id and version all along — into `notes` prose — and
`services.py` then re-derived them by splitting a display string. **Parsing a display string to
decide identity is the mistake [DR-011](DR-011-r8b-identifier-keyed-person-identity.md) already
named once**, and it was sitting one module away the whole time.

### 2. A cross-server reference was keyed in the local scope

`https://radboud.example/fhir/Patient/987` ingested at `mumc` produced the **same IRI** as
mumc's own `Patient/987`. `references.py` even records "names a different server base …
cross-server identity is an identity-policy decision" — and the server base survived only in
`canonical_url`, which is not a key input, so the policy never saw the decision.

### 3. DR-014's fix never reached the operator path

`Pipeline.run_file()` called `source_context(path)`, which ingested with **no scope**, so it
took the single-source default. The operator CLI had no `--source-scope` and no
`--person-index`. So from the only entry point an operator has, two hospitals' `Patient/123`
were **still one person**, and the index could never be supplied at all.

The test I wrote to demonstrate R8b passes because it calls `ingest_file(..., source_scope_id=…)`
itself and then `run_context` — **bypassing `run_file`**. "Demonstrated end to end" was true of
the library path and not of the operator path, and I did not notice the difference.

## The fix

`ReferenceEvidence` carries the parsed target: `target_resource_type`, `target_resource_id`,
`target_version_id`, `target_server_base`. Parsed once, where the parsing already happened.

- **A version is lineage, not identity.** `Patient/123/_history/2` and `Patient/123` are one
  person; the version is retained on the evidence.
- **A reference into another server is refused**, `cross-server-reference-unscoped` — exactly
  parallel to `ID-R9` for a contained reference with no container. Keying it locally would be
  the unrecorded cross-source merge `reference_scope.cross_source_merge` exists to prevent.
  Resolving it properly needs a server-base → scope-id mapping, which is a reviewed decision.
- **`Pipeline` carries `source_scope_id`** and `run_file` uses it; the CLI gains
  `--source-scope` and `--person-index` on both `map` and `batch`.

## Why the existing guard did not catch any of it

`test_no_module_constant_is_used_for_scoping_any_more` checks that
`entity_for_reference`'s **source text** contains `_scope_of(ctx)` and not `SourceScope(SCOPE_ID`.
Review reintroduced the defect while keeping both substrings and ran **630 tests: 0 failures**.

A source-text assertion cannot see behaviour. The replacements in
`tests/contracts/identity/test_reference_target_keying.py` are behavioural, and reintroducing
both defects now fails four of them.

## Smaller findings fixed in the same pass

- **`build()` let a repeated record id overwrite within one Bundle** — `out[key] = …`, last
  wins. `merged_with` checked this across files; nothing checked within one, so DR-015's
  "two indexes disagreeing raise" was true only between files. Now raises either way.
- **`load()` skipped digest verification when the field was absent** (`if recorded and …`), so
  a hand-written index bypassed the check DR-015 promises. An index with no digest is refused.
- **`merged_with`'s conflict raise had no test.** Review deleted it entirely and 637 tests
  passed. Pinned now.
- Three documentation guards were too crude to catch their own cases: the Synthea check was
  case-sensitive, the "items remain open" check keyed on one past phrasing that no longer
  appears, and the answered-item regex read `## R8 — … R8a ANSWERED / R8b OPEN` as answered.
  All three of review's bypasses are now caught. Strengthening the last one then false-flagged
  **R5**, whose *title* contains "open-world" — the same too-crude-matching mistake a third
  time, now fixed by matching `OPEN` as a word.

## Still open from this review

- **Contained candidates are looked up in the index under the raw scope and id**
  (`service.py`), not the effective container-scoped key. Not reachable through the pipeline,
  because `references.py` always emits `#cid`, but a contained resource should never be looked
  up in the index at all.
- **`source_scope_id` is in no graph-key field.** Two sources' `Observation/1` produce different
  person IRIs but the *same* graph key, and the store raises a misdiagnosed
  `StoreIntegrityError` about version reuse. This is DR-016 again with the scope in place of the
  index, and it means multi-source loading fails on the first shared resource id.
- **Alias shadowing is order-dependent** if one entry lists another's primary system;
  `PolicyBundle.validate()` should refuse that.
- An **empty** index records `person_index_digest = "none"`, so a run cannot say it used one.

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
1035 passed
```

Fault injection: restoring `rsplit` **and** disabling the cross-server refusal, while keeping
the substrings the old guard checks, fails 4 behavioural tests. Before, it failed none.
