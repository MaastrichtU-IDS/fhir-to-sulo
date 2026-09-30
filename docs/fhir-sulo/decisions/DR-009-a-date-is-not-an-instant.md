# DR-009 — A date is not an instant, and no SULO Time branch fits one

**Status:** Reviewer constraint given 2026-09-30; consequence **derived**, outcome proposed
**Gate:** 0 (new R3 row)

## The constraint

Reviewer, on whether a date-only `effective[x]` is a `sulo:TimeInstant`:

> **date is not an instant.**

## What that leaves, derived from SULO 0.2.12

`sulo:Time owl:disjointUnionOf ( sulo:Duration sulo:TimeInstant sulo:TimeInterval )`, with a
matching `owl:AllDisjointClasses`. So every `Time` is exactly one of three, and the reviewer has
ruled out one. Taking the other two in turn:

**`sulo:Duration` — no.** *"the extent or (non-negative) amount of time that elapses between two
temporal points"*, with `hasValue` restricted to `xsd:decimal ≥ 0`. A date is a position in
time, not an elapsed amount. `2026-09-02` is not a quantity of hours.

**`sulo:TimeInterval` — not without fabricating.** The class is not merely "a stretch of time":

```turtle
sulo:TimeInterval rdfs:subClassOf
    [ owl:onProperty sulo:hasDirectPart ; owl:someValuesFrom sulo:StartTime ],
    [ owl:onProperty sulo:hasDirectPart ; owl:someValuesFrom sulo:EndTime ] ;
  rdfs:comment "a continuous and bounded extent of time, characterized by a start time
                and an end time."
```

and `StartTime ⊑ TimeInstant`, `EndTime ⊑ TimeInstant` — so both endpoints are instants, each
requiring a `hasValue` of `xsd:dateTime` or `xsd:dateTimeStamp`.

To make `2026-09-02` an interval we would have to mint two instants: a start at
`2026-09-02T00:00:00` and an end at `2026-09-03T00:00:00` — **in some timezone**. The source
gives no offset. Choosing one invents information the record does not contain, which concept
note §2 forbids directly: never drop or add to what the source supports, and preserve unknown
endpoints as unknown.

**Bare `sulo:Time` — no, and for a reason the reviewer has already ruled on.** Because `Time` is
a *disjoint union*, typing an individual as bare `Time` leaves it unpartitioned: a reasoner
knows it is one of the three and cannot say which. That is structurally the same mistake as
bare `sulo:Feature`, which the reviewer rejected in **R4** — *"we should not use feature -> it
should go to a more specific class"*. The same argument applies here.

## Conclusion

**No branch of SULO's Time partition fits a date-only value without fabricating information.**
This is a derivation from the pinned ontology plus the reviewer's constraint, not a preference.

## Proposed outcome: `source-only`

A date-only `effective[x]` is **retained in the source layer and produces no semantic time
node**. The FHIR value, its precision and its datatype survive in the source RDF and the
lineage; the semantic layer asserts nothing it cannot support.

This is the same shape as the existing `dataAbsentReason` outcome: the record is kept, the
unsupported assertion is not made. It is consistent with §2's "preserve time precision and
unknown endpoints" — an unknown offset is preserved by *not* asserting one.

**Not applied yet.** It is a new row in **R3**, which is still open, and R3's other rows should
be answered together. Recorded here so the derivation is available when they are.

## Consequences if the reviewer instead wants it represented

Two routes exist, both requiring a decision rather than a default:

1. **Extend SULO** with a class for a temporally-extended-but-unbounded position — a day
   without an offset. That is an upstream ontology change, out of scope for this pilot, and it
   is the kind of thing the reviewer's note under **R2** already flagged: *"we need to visit
   that in a coherent theory, as compared to other ULOs."*
2. **Adopt a stated timezone policy** — e.g. "a date-only value is interpreted in the source
   system's declared local timezone" — which would make the interval derivable. That is a
   clinical and governance decision, and it would need to be recorded per source, not assumed
   globally. It would also make the derived endpoints *inferences*, which §7 would require to
   be distinguishable from asserted values.

Neither is proposed. They are recorded so that "source-only" is visibly a choice with
alternatives rather than the only thing anyone thought of.
