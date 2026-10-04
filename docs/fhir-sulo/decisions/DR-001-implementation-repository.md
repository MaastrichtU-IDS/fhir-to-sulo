# DR-001 — Implementation repository

**Status:** Decided (Agent 1, integration lead)
**Date:** 2026-09-29
**Gate:** 0

## Context

The implementation plan §1 states the source layout "is a contract for implementation;
choose the repository after a read-only repository review. Avoid scattering generated
graphs and mappings across unrelated codebases."

Three candidate repositories were reviewed read-only.

| Repository | Reviewed | Nature |
| --- | --- | --- |
| `MaastrichtU-IDS/fhir-to-sulo` | tree, git log | Holds the concept note and implementation plan. No code. Default branch `main`, single commit `fc1295c`. |
| `micheldumontier/shexmap-repository` | `CLAUDE.md`, `REQUIREMENTS.md`, tree, `api/src/services/shexmap-validate.service.ts` | Deployed platform: Fastify API + React SPA + QLever triplestore + nginx, orchestrated by Docker Compose. TypeScript. Authoring/versioning UI for ShExMap pairings. |
| `AIDAVA-DEV/sulo` | tree, `versions/sulo-0.2.12.ttl` | The SULO ontology itself, with a `versions/` release series. MIT. |

## Decision

**Implement the pilot in `MaastrichtU-IDS/fhir-to-sulo`**, on branch
`feat/gate0-pilot-contract`, using the directory layout proposed in plan §1.

## Rationale

1. **It already holds the acceptance contract.** The concept note and implementation
   plan are the scope and acceptance criteria for this work. Keeping the implementation
   beside them makes the gate conditions checkable in one place.
2. **It is empty of code**, so the plan's warning about scattering generated graphs and
   mappings across unrelated codebases is satisfied by construction.
3. **The ShExMap Repository is a different product with a different job.** Its own
   `CLAUDE.md` scopes it as "an online repository platform for ShExMaps". Concept note §3
   assigns it the role of *authoring and versioning interface* for mapping pairs, with
   the execution service pinning a reviewed pairing version. Embedding a FHIR pilot in it
   would invert that relationship, couple every pilot test run to a QLever instance and an
   nginx stack, and expand a platform codebase with domain-specific clinical fixtures.
4. **SULO is consumed, not modified.** It is pinned as a read-only dependency (see DR-002).

## Consequences

- Reviewed map pairs are **published to** the ShExMap Repository as a Gate 4 step; they are
  **authored and tested in** this repository. The runtime pins a published pairing ID + hash.
- This repository gains a JS/TS toolchain for the mapping stack (see DR-003) even though the
  host services are Python. That split is accepted because the engine is ShEx.js.
- No changes are proposed to `shexmap-repository` or `sulo` as part of Gates 0-4.

## Prior art carried forward

`shexmap-repository`'s `api/src/services/shexmap-validate.service.ts` (522 lines) is a working
independent implementation of `%Map:{ }` binding extraction and materialization over
`@shexjs/parser`. It is useful reference for the annotation syntax and AST shape. Its
**limitations are load-bearing for our design** and are recorded in DR-004.
