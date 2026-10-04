# DR-014 — The source scope was a module constant, which silently merged people

**Status:** Defect found and fixed 2026-10-04
**Gate:** 0 (identity) · affects every emitted entity IRI in a multi-source deployment
**Trigger:** the reviewer stated that R8b data "will be from a variety of different healthcare systems"

## The defect

`policies/identity-policy.v1.json` has always promised:

> `scoped-hash` — "Source-scoped by construction; **two sources that both hold `Patient/p123`
> get different IRIs.** Safe default."

The policy delivers that. **The pipeline did not call it correctly.**
`src/fhir_sulo/pipeline/services.py` held

```python
SCOPE_ID  = "synthea-pilot-r4"
FHIR_BASE = "https://fhir.example/"
```

as module constants and passed them as the `SourceScope` for **every** resource. So
`Patient/123` at Maastricht and `Patient/123` at Radboud produced **one** entity IRI.

Two different people, fused, with nothing reporting it. That is strictly worse than failing to
merge: a missed merge leaves two records unlinked, which is recoverable; a false merge asserts
that one person has the other's clinical findings.

Measured before the fix:

```
policy, given two scopes:   person-345b40bb…  vs  person-d812962f…   (correct)
pipeline, whatever the source:  person-dde76399…  every time          (the defect)
```

`dataset_id` already existed on `ingest_resource` — and never reached `SourceContext`, so the
pipeline had no way to be told where a resource came from even if a caller wanted to.

## Why no test caught it

**Every fixture in this repo comes from one source.** Under a single-source corpus the constant
is indistinguishable from the correct value, so no assertion could have separated them. Running
the full suite against the unfixed code confirms it: **959 passed, 0 failures.**

This is not a gap in test discipline that more of the same would have closed. It is a defect
that only exists in a configuration the corpus did not contain. The reviewer's one sentence
about deployment was worth more than the whole suite here.

## The fix

The scope is a property of **where the resource came from**, so it travels on the resource:

- `SourceContext` gains `source_scope_id` and `fhir_base_url`.
- `ingest_text` / `ingest_resource` take `source_scope_id` and record it, alongside the
  manifest's `server_base`.
- `pipeline/services.py` reads `_scope_of(ctx)` per resource. The constants remain **only** as
  the pilot's documented default, re-exported from `contracts` so existing callers resolve.
- A context carrying **no** scope raises `source-scope-unknown` rather than defaulting. Keying
  an unknown origin under a default is precisely the merge this prevents.

`CONTRACT_VERSION` **0.4.0 → 0.5.0**.

**No entity IRI in this repo moved**: the pilot default equals the old constant, and the full
suite passes unchanged at 959.

## Consequence for R8b, which is now the main event

`reference_scope.deployment_mode` is now `multi-source`.

With no allowlisted person-identifying identifier, **the same human seen at five systems is five
person entities.** That is the correct conservative outcome under R2b — five records, no
reviewed evidence they are one person — but it is a large effect at scale, and it makes
`person_identifying_identifier_systems` the only mechanism that can ever reunite them.

R8b is therefore no longer an edge case. It is the **primary cross-system identity rule**, and
two things now block it from doing that job:

1. **No real-world identifier system is allowlisted.** Only a synthetic namespace is, so nothing
   real can merge. Which namespaces identify a human remains a reviewer and governance decision.
2. **The rule cannot fire through any shipped map** (DR-011, corrected): every source schema
   requires `Reference.reference`, so a logical reference fails validation first.

Both were acceptable while R8b was a refinement. Neither is, if cross-system identity is the
point of the deployment.

## Guards added

`tests/contracts/identity/test_multi_source_scoping.py`:

- two systems holding one resource id are two people, and two systems behind **one** FHIR base
  are still two people, so `scope_id` alone suffices;
- the same system twice is one person, so scoping did not make keying unstable;
- a context without a scope is refused;
- the pilot default equals the old constant, so adopting the fix re-keyed nothing;
- a source-level guard that `entity_for_reference` no longer builds a `SourceScope` from module
  constants — the *shape* of the bug, not only its symptom.
