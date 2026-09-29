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

Each table carries its own semantic `version`. For a `RunRecord`:

- `PolicyBundle.policy_version` is the single string covering all three, e.g.
  `fhir-sulo-policies/identity-1.0.0+code-1.0.0+unit-1.0.0+sha256.6b2c35b7a7c69f3f`.
  `parse_policy_version()` resolves it back to its components and
  `matches_policy_version()` checks a checkout against it.
- `PolicyBundle.terminology_snapshot` is the single snapshot string.

`PolicyBundle.versions` keeps the per-table detail behind those.

### Entity IRIs do not move when a version does

`entity_iri.key_revision` and `quality_identity.key_revision`, **not** the table
versions, are what entity and quality IRIs are keyed on. Bumping a table version,
adding a code entry or approving a unit leaves every IRI unchanged; bumping a
`key_revision` re-keys everything and needs its own DR-4xx record. Policy
validation rejects a table that tries to key on `policy_version`.

The one intended exception: answering the quality identity question changes every
quality IRI, because the two modes key on different inputs.

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
