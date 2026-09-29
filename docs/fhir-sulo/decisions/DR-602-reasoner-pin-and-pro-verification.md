# DR-602 — OWL reasoner pin, and the PRO property-chain verification

**Status:** Decided (Agent 6), with the verification output reproduced below
**Date:** 2026-09-29
**Gate:** 3 (the PRO entailment) and 4 (the benchmark)
**Depends on:** DR-002 (SULO 0.2.12 pin and the confirmed chain axiom)

## Pin

| Item | Value |
| --- | --- |
| Reasoner | **HermiT**, via ROBOT |
| ROBOT | `obolibrary/robot:v1.9.7` |
| Image digest | `sha256:58da5acb0bb861ca84409213f2b6e15ab41eda145e602ef5cfdf87d974ec5976` |
| Axiom generators | `PropertyAssertion ClassAssertion` |
| Tautology exclusion | `-t structural` (load-bearing — see §4) |
| Ontology | SULO 0.2.12, vendored at `src/fhir_sulo/validation/ontology/sulo-0.2.12.ttl`, sha256 `ea4bd090e5677db18446b255b81c6c8f844c2d6e4e29424bacf13b06d29e5c8c` |

Pinned **by digest, not by tag**: a tag can be repointed at a different build.
SULO is **vendored**, so the reasoning tests run offline and an upstream force-push cannot
change what the pilot was verified against; a test checks the digest against DR-002's pin.

There is no `java` on the pilot host, so ROBOT runs in Docker. The prohibition on a JVM
dependency is scoped to the mapping stack; a JVM reasoner is acceptable. Where `robot` *is* on
`PATH` — as in the Gate 4 benchmark image, which carries the jar copied from the same digest —
it is invoked directly, so the JVM shares the measured cgroup.

## The entailment under test

SULO 0.2.12 (DR-002, re-verified here against the vendored copy):

```turtle
sulo:hasParticipant owl:propertyChainAxiom
    ( sulo:hasParticipant [ owl:inverseOf sulo:hasFeature ] ) .
```

From `encounter hasParticipant role` + `role isFeatureOf person`, a reasoner must entail
`encounter hasParticipant person`.

A property chain containing an **inverse** property is outside OWL 2 EL. So the reasoner must be
OWL 2 DL — and a weaker one does not complain, it returns fewer entailments and exits 0. The
brief required this be verified rather than read off a feature table.

## Verification output

`python -m fhir_sulo.validation.cli reasoner-check`, on the tiny hand-written graph in
`reasoning.PRO_PROBE_TTL`:

```
reasoner:                 HermiT
image:                    obolibrary/robot@sha256:58da5acb0bb861ca84409213f2b6e15ab41eda145e602ef5cfdf87d974ec5976
entailment materialized:  True
refutation detected:      True
expected inferred triple: <https://example.org/fhir-sulo/encounter-9> <https://w3id.org/sulo/hasParticipant> <https://example.org/fhir-sulo/person-p123>
verdict:                  USABLE
  materialization: 89 inferred triples; expected triple PRESENT
  refutation: reasoner reported the denial inconsistent, so it does entail the triple
```

**Two independent checks**, because either alone can pass for the wrong reason:

1. **Materialization** — reason over the probe and look for the triple among the inferences.
2. **Refutation** — reason over the same graph plus an explicit `owl:complementOf`
   `owl:hasValue` denial of that triple, and require the ontology to be reported
   **inconsistent**. This asks the *reasoner*, not the serialiser, and cannot be satisfied by an
   axiom generator that was wrong in our favour.

§4 records a case where check 1 passed and check 2 failed, and check 2 was right.

### The negative control

Run through the same code path, ELK (OWL 2 EL) must be found **not usable**:

```
reasoner:                 ELK
entailment materialized:  False
refutation detected:      False
verdict:                  NOT USABLE
  materialization: 63 inferred triples; expected triple ABSENT
  refutation: reasoner accepted a graph that denies the entailment, so it does not entail it
```

ELK produced 63 inferred triples, exited 0, and said nothing. That is exactly the silent failure
the brief warned about, and it is why the verification exists.

`tests/integration/test_reasoning_pro.py` asserts HermiT is usable **and** ELK is not, so the
test fails if the reasoner is swapped for one that cannot do this — and the ELK case proves the
test is capable of failing.

## Two traps found while building this

### Trap 1 — `robot merge -i ontology.ttl -i data.ttl` silently loses the entailment

OWLAPI parses each input file as its own RDF-to-OWL unit. `data.ttl` declares no object
properties, so the participation triples are parsed as **`AnnotationAssertion`**. Annotations
carry no semantics, the chain never fires, and the output looks plausible. Exit code 0.

Measured on this host:

| invocation | how the triples parse | entailment |
| --- | --- | --- |
| two `-i` inputs | `AnnotationAssertion(sulo:hasParticipant …)` | **absent** |
| one merged input | `ObjectPropertyAssertion(…)` | present |

So `materialize` merges the ontology and the data into **one parse unit** with rdflib before
calling ROBOT. `probe_separate_parse_units()` reproduces the trap and a test pins it, so the
merge cannot be "simplified away" by someone who does not know why it is there.

### Trap 2 — declaring OWL structural vocabulary dismantles class expressions

The merge step also declares domain terms the ontology does not (otherwise trap 1 recurs for
`ex:` predicates). An early version declared **everything** undeclared, including
`owl:complementOf`, `owl:onProperty` and `owl:hasValue`, as object properties. OWLAPI then
re-read the refutation's class expression as three plain assertions, and the restriction stopped
constraining anything.

The symptom: materialization still passed, refutation started failing. **The refutation check
caught a bug in our own pipeline**, which is the strongest argument for having both halves.
`_STRUCTURAL_NAMESPACES` now excludes RDF, RDFS, OWL and XSD from declaration.

## 4. `-t structural` is a correctness and scale requirement, not tuning

SULO makes `hasPart`, `contains` and `isIn` reflexive and transitive, and every individual is
related to every other by `owl:topObjectProperty`. The property-assertion generator therefore
emits O(n²) triples per batch that say nothing. Measured on 40 synthetic encounters (1,508 input
triples):

| setting | time | inferred lines | of which `topObjectProperty` |
| --- | ---: | ---: | ---: |
| `-A PropertyAssertion` | 2.65 s | 95,949 | 305 |
| `+ -t structural` | 1.95 s | **2,924** | 0 |

A 33× reduction and a quadratic term removed. The PRO entailment is **not** a tautology and
survives; the verification above is run with the setting active, so that is checked rather than
assumed.

## 5. Batching

The PRO chain is local to one encounter — it never crosses resources — so reasoning is done in
batches (default 100 encounters). This is sound rather than a shortcut: no entailment the pilot
depends on relates two source resources. Reasoning 10,000 resources as one ontology asks HermiT
for global work the semantics do not require and does not finish in useful time. Measured:
~21 encounters/s, 92 s for 1,959 encounters on the 4-vCPU runner.

If a later map ever introduces a cross-resource entailment, this batching becomes unsound and
must be revisited. Nothing in Gates 0–4 does.

## 6. What was rejected

| Option | Why not |
| --- | --- |
| **ELK** | OWL 2 EL has no inverse properties. Cannot do this chain, and says so by silence. Kept as the negative control. |
| **owlready2** (bundles HermiT) | Still needs a JVM, so it buys nothing on a host with no `java`, and pins the reasoner less precisely than an image digest. |
| **Hand-coding the chain** in SPARQL/rdflib | Fast and wrong in principle: it would make the "reasoner checks expected PRO entailments" validation layer (concept note §7) a check of our own code against itself, and it would not notice a SULO axiom change. |
| **JFact** | An OWL 2 DL alternative and a reasonable fallback, not evaluated. Recorded as an option if HermiT ever becomes a bottleneck; it is not one at 21 encounters/s. |
