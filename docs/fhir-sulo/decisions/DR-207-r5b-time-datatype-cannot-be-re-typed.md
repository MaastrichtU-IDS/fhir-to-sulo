# DR-207 — R5b: ShExMap cannot re-type a literal, so the time datatype cannot discriminate

**Status:** Measurement stands; **R5c withdrawn 2026-10-01**.
The engine findings below are unaffected and are cited by CD-7. What changed is
their consequence: R5c assumed an offsetless instant could occur, and it cannot.
FHIR R4's published `dateTime` regex does not make the timezone optional, so
every conformant value that renders `xsd:dateTime` carries an offset and the
reviewer's "time instants are specified in the has value datatype" holds as
stated. Nothing to implement. See `test_every_emitted_instant_carries_an_offset.py`
for the positive property on real fixtures.
**Date:** 2026-09-30
**Gate:** 2 / 3
**Owner:** Agent 3 — mapping author
**Arises from:** R5 row 2 = B (relax), answered 2026-09-30
**Depends on:** DR-301 (engine capability), DR-101 (the renderer's HL7 oracle), rule 4

## What was asked

R5 row 2 was answered **relax** — no `sulo:Unit` on a time instant. Reviewer:
*"time instants are specified in the has value datatype."*

That makes the datatype load-bearing, so the instruction was: emit
`xsd:dateTimeStamp` when the source value carries an offset and `xsd:dateTime`
when it does not, so the datatype records what was actually known. Not by
changing the source RDF — HL7's published Turtle types offset-bearing values
as plain `xsd:dateTime`, and Agent 2's renderer is validated
graph-isomorphically against those files.

## Why it cannot be done

Three measurements, each pinned by a test in
`tests/contracts/maps/test_r5b_time_datatype.py` so the conclusion cannot rot
into a comment nobody rechecks.

**1. The materializer re-emits the bound source term verbatim. A target
constraint's declared datatype is ignored.**

```
target:   sulo:hasValue xsd:dateTimeStamp %Map:{ v:effective %}
source:   "2026-09-02T14:00:00Z"^^xsd:dateTime
emitted:  "2026-09-02T14:00:00Z"^^xsd:dateTime        <- not dateTimeStamp
```

Same for `+01:00` and for an offsetless value. Declaring `dateTimeStamp` in a
target schema simply does nothing.

**2. Declaring it anyway is worse than a no-op — the graph then fails its own
schema.** Reverse-validating a materialized graph against the target schema
that produced it is the pivot-recovery check the concept note §5 asks for. A
target declaring a datatype the engine will not emit breaks it:

| the target declares | reverse validation of the emitted graph |
| --- | --- |
| `xsd:dateTime` | passes |
| `xsd:dateTimeStamp` | **fails** |

This is the same class of defect as DR-201 §5.2: a schema that does not
describe its own output.

**3. ShEx datatype matching is exact, not subtype-aware.** `xsd:dateTimeStamp`
is a subtype of `xsd:dateTime` in XSD, but ShEx matches the literal's datatype
IRI. A `dateTime` literal does not satisfy a `dateTimeStamp` constraint, or
the reverse. So the source shape cannot read it as a `dateTimeStamp` either —
and the source RDF is not ours to re-type.

**The remaining routes are both prohibited.** Supplying the literal as a
host-built `staticVar` moves target triple construction into the host, which
rule 4 forbids; re-typing after materialization is a postprocessor, forbidden
outright. Neither is a workaround worth having: the value would then be one
the host wrote, not one the map extracted.

## What the maps emit today, side by side

```
offset-bearing   ex:time-egfr-456 sulo:hasValue "2026-09-02T14:00:00Z"^^xsd:dateTime
offsetless       ex:time-egfr-456 sulo:hasValue "2026-09-02T14:00:00"^^xsd:dateTime
other offset     ex:time-egfr-456 sulo:hasValue "2026-09-02T14:00:00+05:30"^^xsd:dateTime
```

The offset is preserved when there is one and never invented when there is
not, which is what §2 requires. What the datatype does *not* do is tell the
two cases apart — which is precisely the gap R5b identified and which this
engine cannot close.

The third line is the injection that shows nothing is hard-coded: a map that
pinned `Z`, or normalised every instant to UTC, passes the first two tests and
fails that one.

## What IS available: the source can discriminate

Proved, and worth stating because it means an answer is implementable even
though re-typing is not. A ShEx regex facet tells the lexical forms apart, and
a `ShapeOr` binds a different variable per branch:

```shex
fhir:Observation.effectiveDateTime (@sh:Offset OR @sh:Offsetless)

sh:Offset     CLOSED { fhir:value xsd:dateTime /(Z|[+-][0-9]{2}:[0-9]{2})$/ %Map:{ v:withOffset %} }
sh:Offsetless CLOSED { fhir:value xsd:dateTime /[0-9]$/                     %Map:{ v:noOffset %} }
```

Verified for `Z`, `+01:00`, `-05:00` and an offsetless value. So the map can
*act* on the distinction — it just cannot act by changing the datatype.

## R5c, for the reviewer

> Under R5's answer the datatype carries the specification of an instant, but
> the pinned engine cannot emit a datatype other than the one the source
> carries, and the source is `xsd:dateTime` for every instant including
> offset-bearing ones (HL7's own convention). So an offsetless instant and a
> UTC instant are both `xsd:dateTime` and differ only in lexical form. How
> should an offsetless instant be treated?

- **A. Accept it as is** (current behaviour). The lexical form carries the
  offset when there is one; only the datatype IRI fails to discriminate.
  Nothing to build.
- **B. Reject it.** Add the offset regex facet to `effectiveDateTime`,
  `Period.start` and `Period.end`; an offsetless value fails source validation
  and the resource stays `source-only`. One line per time constraint,
  conservative, and consistent with how every other open item is held — but it
  rejects legitimate FHIR.
- **C. Mark it in the graph.** Alternative target shapes selected by the
  discrimination above, adding a domain class beside `sulo:TimeInstant` for
  the offsetless case. No re-typing, the resource stays mappable, and the
  under-specification becomes explicit and queryable. Costs one new vocabulary
  entry, which is R1's owner's call.

**Engineering recommendation, not a decision: C, with B as the conservative
fallback.** C keeps the resource, makes the under-specification first-class
rather than implicit in a string, and needs no capability the engine lacks.

Rejected without asking: changing the renderer to emit `xsd:dateTimeStamp`.
It would break the external oracle that stops the renderer being
self-certified, and that check is worth more than the convenience — the
integration lead said as much, and the measurement above shows it would not
have helped anyway, because the *target* would still re-emit whatever the
source carried.

## The rdflib asymmetry, since it was asked about

Measured, and relevant if option C or any future work ever does emit both
datatypes:

| datatype | `…T14:00:00Z` serialises as |
| --- | --- |
| `xsd:dateTime` | `…T14:00:00+00:00` — **rewritten** |
| `xsd:dateTimeStamp` | `…T14:00:00Z` — left alone |

An explicit `+01:00` is untouched either way. Graph comparison and the SHACL
digest both go through rdflib, so the same instant would have different
lexical forms depending on its datatype. Pinned by
`RdflibCanonicalisesTheTwoDatatypesDifferently`.

## Asks

- **A fixture with an offsetless `effectiveDateTime`** (Agent 2). Every
  fixture currently carries `Z`, so the offsetless case is exercised here by a
  **labelled perturbation** of `egfr-baseline`'s rendered RDF, clearly marked
  as such in the test. A real fixture would be better evidence, and would also
  give `fixtures/expected/` a golden for the case.
- **Whether this warrants a CD entry** (integration lead). It changes what an
  acceptance row can mean — "time instants are specified in the has value
  datatype" is not achievable as stated. I have not edited
  `CONTRACT-DEVIATIONS.md`, per the standing instruction about who owns it.
- **R5 row 2 itself is unaffected.** No `sulo:Unit` on any time node;
  `R5Row2StaysRelaxed` asserts it across the eGFR and Encounter maps,
  including `sulo:StartTime` and `sulo:EndTime`.
