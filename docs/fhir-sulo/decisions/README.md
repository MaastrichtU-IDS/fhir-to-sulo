# Decision records

45 records. The numbering is by owner, not by date: **DR-0xx** integration and reviewer
rulings, **DR-1xx** ingestion, **DR-2xx** maps, **DR-3xx** engine, **DR-4xx** identity and
terminology, **DR-6xx** provenance, validation and operations.

If you are reviewing this for the first time, the records marked **★** are the ones where
something was *wrong* and had to change. They are the useful ones; the rest record choices that
held.

## Reviewer rulings and integration (DR-0xx)

| | record | what it settles |
| --- | --- | --- |
| | [DR-001](DR-001-implementation-repository.md) | which repository to implement in |
| | [DR-002](DR-002-sulo-pin-and-axioms.md) | SULO pinned by commit; which axioms actually exist |
| | [DR-004](DR-004-shexmap-repository-prior-art.md) | what the prior art proves, and what it cannot |
| ★ | [DR-005](DR-005-entity-iri-style-and-agent5-scope.md) | entity IRI style — a decision recorded and never applied for four days |
| | [DR-006](DR-006-agent2-integration-decisions.md) | ingestion's open points |
| ★ | [DR-007](DR-007-integration-record.md) | merges, defects found, and open debt |
| | [DR-008](DR-008-domain-vocabulary-and-its-successor.md) | mint a local vocabulary now, RAG over OMOP later |
| | [DR-009](DR-009-a-date-is-not-an-instant.md) | a date is not an instant, and no SULO Time branch fits one |
| ★ | [DR-010](DR-010-ontoclean-practitioner-is-a-role.md) | **R8a.** "practitioner" was an identity criterion. OntoClean forbids it |
| | [DR-011](DR-011-r8b-identifier-keyed-person-identity.md) | **R8b.** a person identifier *keys* the person; it is not a merge pass |
| ★ | [DR-012](DR-012-r9-vitalsigns-conformance-and-the-panel-code.md) | **R9.** a conformance claim nothing checked; a panel coded as systolic |
| | [DR-013](DR-013-r12-participation-type-types-the-role.md) | **R12.** the participation type types the role node |
| ★ | [DR-014](DR-014-the-source-scope-was-a-module-constant.md) | **the scope was a constant, so two hospitals' patients became one person** |
| | [DR-015](DR-015-person-identifier-index.md) | the index, because a BSN lives on a resource we never ingest |
| ★ | [DR-016](DR-016-the-index-belongs-in-the-graph-key.md) | one graph key named two different graphs |
| ★ | [DR-017](DR-017-one-identifier-system-has-several-spellings.md) | BSN arrives as a URI *and* as a `urn:oid:`; exact matching missed one |
| ★ | [DR-018](DR-018-the-key-triple-came-from-string-surgery.md) | **three false merges: a versioned reference named the wrong patient** |
| ★ | [DR-019](DR-019-the-source-scope-was-in-no-key-field.md) | two hospitals shared one replacement slot, so one superseded the other |
| ★ | [DR-020](DR-020-contained-fusion-alias-shadowing-and-the-canonical-url.md) | a contained resource fused with a top-level patient; two smaller holes |
| ★ | [DR-021](DR-021-a-flag-that-could-not-be-used-and-guards-that-did-not-guard.md) | --fhir-base broke every run; three features could be switched off, suite green |

## Ingestion (DR-1xx)

| | record | what it settles |
| --- | --- | --- |
| | [DR-101](DR-101-fhir-rdf-renderer.md) | the renderer, validated against HL7's own published Turtle |
| | [DR-102](DR-102-fixtures-and-binding-tuples.md) | fixture layout and the expected-binding format |
| | [DR-103](DR-103-identity-service-interface.md) | what ingestion needs from identity |

## Maps (DR-2xx)

| | record | what it settles |
| --- | --- | --- |
| | [DR-201](DR-201-map-architecture-and-shexmap-limits.md) | map pair architecture, and what ShExMap could not express |
| | [DR-202](DR-202-expected-graphs-and-negative-outcomes.md) | expected graphs and negative outcomes |
| ★ | [DR-203](DR-203-the-acceptance-check-was-on-the-wrong-artifact.md) | the Gate 3 check was asserting over the wrong artifact |
| ★ | [DR-204](DR-204-the-gate-suite-must-be-order-independent-and-pinned.md) | the suite had to pass from clean, in any order |
| | [DR-205](DR-205-tolerated-source-only-elements-and-the-method-conflict.md) | tolerated source-only elements, and the `method` conflict |
| | [DR-206](DR-206-r4-r6-r11-applied.md) | R4, R6 and R11 applied |
| | [DR-207](DR-207-r5b-time-datatype-cannot-be-re-typed.md) | R5b: the engine cannot re-type a literal |
| | [DR-208](DR-208-r3-the-revision-axis-is-eligible.md) | R3: status has two axes, and the revision one is eligible |

## Engine (DR-3xx)

| | record | what it settles |
| --- | --- | --- |
| | [DR-301](DR-301-engine-pin-and-capability-verdict.md) | the engine pin and the Gate 1 capability verdict |
| ★ | [DR-302](DR-302-one-repetition-per-path.md) | two-level repetition is silently wrong upstream |
| | [DR-303](DR-303-engine-host-tools.md) | the schema-pair linter and the materializer |
| | [DR-304](DR-304-composed-pipeline-and-map-linting.md) | lint a map, not a shape |
| ★ | [DR-305](DR-305-resident-engine-and-one-graph-key.md) | a resident engine, and deleting the second graph key |

## Identity and terminology (DR-4xx)

| | record | what it settles |
| --- | --- | --- |
| | [DR-401](DR-401-identity-service-interface.md) | interface, keying scheme, ambiguity contract |
| | [DR-402](DR-402-terminology-and-ucum-policy.md) | pinned snapshot; explicit refusals |
| | [DR-403](DR-403-node-identity-convergence-proposal.md) | one owner for node identity — **proposal, not implemented** |

## Provenance, validation, operations (DR-6xx)

| | record | what it settles |
| --- | --- | --- |
| | [DR-601](DR-601-graph-key-and-correction-semantics.md) | the deterministic graph key, and what a correction replaces |
| | [DR-602](DR-602-reasoner-pin-and-pro-verification.md) | the reasoner pin and the PRO property-chain verification |
| | [DR-603](DR-603-shacl-for-target-validation.md) | SHACL for target validation, and the R5 strictness switch |
| | [DR-604](DR-604-benchmark-protocol-and-gate4-result.md) | the benchmark protocol and the Gate 4 result |
| | [DR-605](DR-605-r5-unset-rejects-and-validation-on-map-output.md) | R5 unset rejects; validation moved onto real map output |
| ★ | [DR-606](DR-606-gate4-scale-measured-on-the-real-pipeline.md) | Gate 4 scale **missed** by 5.2×, diagnosed, then fixed 20.5× |

## Numbering

DR-003 does not exist. Numbers are not reused.
