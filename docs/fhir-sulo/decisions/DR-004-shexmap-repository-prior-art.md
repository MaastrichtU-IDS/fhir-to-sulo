# DR-004 — ShExMap Repository prior art: what it proves and what it cannot do

**Status:** Finding (input to Gate 1)
**Date:** 2026-09-29
**Gate:** 0 → 1

## What was reviewed

`micheldumontier/shexmap-repository`, file
`api/src/services/shexmap-validate.service.ts` (522 lines, TypeScript), read-only.

It is a **working, independent implementation** of ShExMap-style binding extraction and
materialization, built directly on `@shexjs/parser` — **not** on `@shexjs/extension-map`.
It powers the repository UI's "Validate" and "Validate & Materialise" actions.

## What it proves (useful to us)

- `%Map:{ var %}` annotations are readable from the parsed ShEx AST as semantic actions
  under `name === "http://shex.io/extensions/Map/#"`, with the variable in `act.code`.
- A `regex(/.../)` form with named capture groups is also supported, and is reversible for
  materialization by substituting bindings back into the named groups.
- Materialization can be driven by walking the target schema AST and emitting a quad per
  annotated triple constraint. Constant `NodeConstraint` values materialize as fixed triples.
- The overall two-schema shared-variable approach is implementable in a few hundred lines.

## What it cannot do (load-bearing for our design)

These are not criticisms of that project — its job is interactive single-example authoring.
They are hard blockers for **our** acceptance contract.

1. **No repetition scopes. Bindings are flat.**
   The materializer's signature is `bindings: Record<string, string>` — one value per
   variable, globally. Two blood-pressure panels cannot be represented: the second panel's
   systolic value overwrites the first, or is dropped.
   *Directly blocks plan Gate 3 and acceptance row "Repetition".*

2. **One node per shape-reference constraint, by construction.**
   `walkTriple` claims the first unclaimed blank node and then `break`s, with the comment
   "one node per shape-reference constraint". A `sourceRef`/`claimed` set exists specifically
   to stop sibling constraints stealing each other's blank nodes — evidence the authors hit
   the repeated-`fhir:component` problem and bounded it rather than solved it.
   *An `Observation` with systolic and diastolic components yields one component, not two.*

3. **No deterministic node identity.** Target nodes are minted as blank nodes from a
   positional counter (`DataFactory.blankNode('b' + counter.n++)`). There is no `id(...)`
   equivalent and no way to key a node from bound variables.
   *Directly blocks the plan's deterministic output graph key, idempotent reprocessing
   (Gate 4: "unchanged reprocessing changes no triples"), and versioned graph replacement,
   all of which need stable IRIs rather than positional blank nodes.*

4. **No per-quad lineage.** Quads are accumulated into a flat array with no record of the
   binding or constraint that produced them.
   *Directly blocks the acceptance row "Lineage".*

## Consequence for Gate 1

We must not adopt this implementation as the pilot engine, and we must not silently
reimplement it. The Gate 1 engine spike (Agent 4) is therefore load-bearing: it must
establish whether the real `@shexjs/extension-map` supports iteration scopes, `id(...)`,
lineage, and inverse recovery.

Decision tree, to be resolved by the Agent 4 findings:

- **`extension-map` supports them** → pin it; author maps against it. Preferred.
- **`extension-map` partially supports them** → pin it, and record each gap as an explicit
  decision with a named owner. A gap handled host-side must be written down here, never
  buried in a postprocessor (plan §6 rule 2, and the user's explicit instruction).
- **`extension-map` does not support them** → escalate. Options are a pinned git build, an
  upstream patch, or a scope change to the acceptance contract. Weakening the BP tuple test
  to make a flat-binding engine pass is **not** an available option.

Nothing downstream of this decision (Agent 3's maps) should be authored until it is resolved.
