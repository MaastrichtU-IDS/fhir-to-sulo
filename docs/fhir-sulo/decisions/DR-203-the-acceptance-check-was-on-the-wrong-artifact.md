# DR-203 — The Gate 3 acceptance check was on the wrong artifact

**Status:** Defect found in review, fixed, and turned into a rule
**Date:** 2026-09-29
**Gate:** 3 (and Gate 2 by the same argument)
**Found by:** independent review, reproduced by the integration lead
**Owner of the defect and the fix:** Agent 3
**Supersedes the claim in:** DR-202 §"Why the golden graphs are not the acceptance conditions"

## What was wrong

The headline Gate 3 assertion — concept note §5's
`{(bp-1,120,80),(bp-2,105,70)}` — was computed from `bp_case.binding_tree`,
which builds `BindingNode`s out of `_sourceBindings`: the bindings the
**source** schema extracted. The **target** graph was never consulted.

So a target schema that bound the right values and emitted the wrong ones
passed. One token proves it. In `maps/r4/bp/bp-target.v1.shex`, change the
diastolic node's

```shex
  sulo:hasValue xsd:decimal %Map:{ v:diaValue %} ;
```

to `%Map:{ v:sysValue %}`, run `python3 maps/r4/rehash.py` so the pairing hash
is legitimate, and the suite reported:

```
1 failed, 20 passed
  the only failure: BPCrossJoinIsDetectable::
      test_injecting_a_wrong_value_into_the_engine_changes_the_graph
  test_the_concept_note_multiset_is_exactly_right ................ PASSED
```

while the emitted graph said

```
<…/bp-diastolic-result-bp-1> <https://w3id.org/sulo/hasValue> "120"^^xsd:decimal .
```

bp-1's diastolic pressure is 80. A graph asserting 120 is clinically wrong,
and the gate's headline test called it correct.

## Why my own fault injection missed it

I injected faults into the **source** schema — swapping the two components'
LOINC codes — and the tests caught them, so I reported the multiset as
verified. Swapping the codes changes what gets bound, which a source-side
assertion can see. It tested the half that was already covered.

The lesson generalises past this bug:

> **A fault injection only demonstrates coverage of the artifact it perturbs.**
> Injecting into the source schema says nothing about whether the target
> schema is checked. Every artifact on the path — source schema, binding tree,
> target schema, emitted graph — needs its own injection.

## The rule

> **An acceptance condition is asserted on the emitted target graph.**
> The target graph is what reaches a clinical store. Bindings are an
> intermediate; asserting over them tests extraction, which is worth doing and
> is not the gate.

Where a source-side assertion is kept, it is named and scoped as
corroboration: `BPSourceBindingMultiset` exists because it localises a fault to
the extraction half, which a target-side check alone would misattribute.

## The fix

`_engine/graph.py::bp_panel_tuples(nquads, vocabulary)` recovers the multiset
by walking the emitted graph and nothing else:

```
panel record --sulo:refersTo--> quantity --sulo:hasValue--> the value
                                   |
                                   +--sulo:refersTo--> quality --rdf:type--> the slot
```

Notes on the choices:

- **The slot comes from the quality's class**, which is the structure concept
  note §5 specifies ("materialize `sulo:Quantity → sulo:refersTo →` a typed
  systolic or diastolic quality"). Nothing is inferred from how a node IRI is
  spelled, from triple order, or from a binding.
- **The quantity's own domain type must agree with its quality's class**, or
  the extractor raises rather than picking a slot. So a graph where the
  diastolic quantity refers to the systolic quality is caught as a structural
  contradiction, not merely as a wrong number.
- **The panel key is read from the emitted `prov:wasDerivedFrom`.** The panel
  id is not a literal anywhere in the target graph, so the graph's own
  statement about which resource a node came from is the only graph-side
  answer to "which observation is this".
- `nquads` is a plain string, so **the producer is swappable**: the test
  harness, Agent 4's driver, or a file. The repoint Agent 4 is planning needs
  no change here.

The same audit was run on eGFR and Encounter (§"Audit" below), and
`test_inverse_pivot.py` now revalidates a **freshly materialized** graph
instead of the committed golden, which would have made it blind to exactly the
drift it exists to catch.

## Audit: which assertions were already target-side

Requested by the integration lead for an honest gate report.

| Assertion | Before | Now |
| --- | --- | --- |
| **BP** multiset, all 5 fixtures + 2 RDF variants | **source bindings only** | emitted graph (`BPTargetGraphMultiset`), plus source bindings as named corroboration |
| BP "each quantity has one value, one unit, one quality" | target graph, **arity only** — counted arcs, never checked which value | target graph, arity **and** content: value, unit IRI and quality IRI all asserted |
| BP no `hasPatient` / predicate allow-list | target graph | unchanged |
| BP orphan nodes, blank nodes, panel typing (R9) | target graph | unchanged |
| BP persons distinct in `bp-other-patient` | host values | unchanged (corroboration), plus the target-graph tuple check |
| **eGFR** one value / unit / quality / patient association | target graph, against literals from the concept note | unchanged, **plus** a cross-check that the emitted value, unit and time equal what the source bound, and that the domain type is the code table's entry for the code the source bound |
| eGFR orphan nodes, blank nodes, SULO axioms, R1 swap | target graph | unchanged |
| **Encounter** roles, PRO entailment, no `hasPatient` | target graph | unchanged, **plus** a per-endpoint check that start and end are the ones the source bound (so a swap fails) and that the patient role is held by the subject and not the practitioner |
| Encounter `AMB` not emitted | source bindings + target graph | unchanged (it asserts an *absence* in the graph, which is the right side) |
| Inverse / pivot recovery, all three maps | target graph, but the **committed golden** | freshly materialized graph |

Summary for the gate report: **one headline condition was on the wrong
artifact (the BP multiset), one was target-side but content-blind (BP quantity
arity), and one read a committed golden rather than fresh output (inverse
recovery). Everything else was already target-side.**

## Two harness defects found while fixing this

Two more, found in the next review round, are in
[DR-204](DR-204-the-gate-suite-must-be-order-independent-and-pinned.md):
the suite was order-dependent and failed from clean, and it was not running
on the pinned image at all.


Both were producing wrong or unstable results and are worth recording because
they are the kind of thing that makes a green suite meaningless.

1. **The job document was raced.** `run_job` `docker cp`'d the job to a fixed
   `/w/job.json` and then `docker exec`'d the runner. `docker cp` returns when
   the daemon has accepted the archive, so a run could read the *previous*
   call's job and materialize the wrong fixture. The BP suite was
   non-deterministic across runs — three consecutive runs gave three different
   failure sets. The job now goes in on **stdin**, which has no such window.
   The suite is deterministic across repeated runs and twice as fast.
2. **The container tree was shared between processes.** `CONTAINER_REPO` was a
   fixed `/w/repo`, and `fixtures/expected/build.py` runs as a subprocess from
   one of the tests and re-synced the same path, so a parent that had already
   synced could go on believing its copy was current. It is now per-process,
   and the sync verifies that the copy landed instead of trusting `docker cp`'s
   exit status.

## Verification

Both injections re-run after the fix, with the pairing hash legitimately
recomputed each time — see the Gate 2/3 report for the transcript. The
diastolic-emits-`v:sysValue` injection now fails five tests in
`test_bp_gate3.py`, including
`test_the_concept_note_multiset_is_exactly_right`; the mirror injection
(systolic emitting `v:diaValue`) fails the same set.
