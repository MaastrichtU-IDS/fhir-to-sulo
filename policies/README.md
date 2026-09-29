# Policy tables

Owner: Agent 5 (identity and terminology). These are the versioned,
machine-readable, human-reviewable tables that the host services in
`src/fhir_sulo/identity/` and `src/fhir_sulo/terminology/` obey. No rule that
affects the produced graph lives in code without a corresponding entry here.

| File | What it governs |
| --- | --- |
| `identity-policy.v1.json` | Reference-to-entity keying, source scoping, ambiguity outcomes, lineage, and the (unset) quality identity mode. |
| `code-interpretation.v1.json` | Which source codes have a reviewed interpretation to a domain class, and what happens to the ones that do not. |
| `unit-policy.v1.json` | Which UCUM codes are pinned, their dimensions and IRIs, and what happens to unknown or incompatible units. |

## Versioning

Each table carries its own semantic `version`. `PolicyBundle.versions` returns
those plus `policy_bundle_digest`, a sha256 over the canonical form of all three
tables. That digest is the single value Agent 6 records as the policy version in
a `RunRecord`; it changes if any byte of any table changes.

```
$ python -m fhir_sulo.policy.report        # Markdown view of all three tables
```

The rendered report is generated on demand, never committed, so there is no
second copy to drift from the JSON.

## Review status

`approved` is the only status that means a human clinical/ontology reviewer
signed the entry off. `pilot-provisional` means the entry was taken verbatim
from the concept note's worked examples so the engineering gates can run on
synthetic data; it is interpretable but every outcome carries
`clinical_signoff: false`. `proposed` and `rejected` are not interpreted.

Nothing is `approved` yet. See `docs/fhir-sulo/decisions/DR-401` and `DR-402`
for the questions waiting on the reviewer.

## Changing a table

1. Edit the JSON. Bump its `version`.
2. Run `python -m pytest tests/contracts -q`; several tests assert the shape and
   the pinned scope of these tables on purpose, so an unintended widening fails.
3. Record the change in a DR-4xx decision record if it changes meaning, not just
   coverage.
