# `profiles/` — the pinned FHIR release, profile set and element scope

Owner: Agent 2 (FHIR ingestion). Consumed by `src/fhir_sulo/ingest/` and by
`MapContract`/`SourceContext`.

Two machine-readable files, both plain JSON so `tools/gate-check.py` can parse
them:

| File | What it pins |
| --- | --- |
| `fhir-r4-pilot.json` | release, source server base, renderer identity and options, profile set per resource, in-scope vs source-only elements, code systems and pinned codes, unit systems and pinned UCUM codes, status policy, value policy, temporal precision policy, terminology snapshot |
| `fhir-r4-element-table.json` | the FHIR element → RDF predicate table for the pinned subset, plus the primitive → xsd datatype map |

Nothing in `src/fhir_sulo/ingest/` hard-codes a LOINC code, a UCUM unit or an
element name. `test_manifest.py::test_no_hardcoded_loinc_or_ucum_outside_the_manifest`
enforces that, so a policy change is a reviewable manifest diff rather than a
code change.

## The pins

**Release.** FHIR **R4, 4.0.1** (`hl7.fhir.r4.core#4.0.1`). The renderer
refuses anything else; R5 is a separate compatibility track with its own
element table (plan §1).

**Profiles.**

| Resource | Canonical | Version | Role |
| --- | --- | --- | --- |
| Observation | `http://hl7.org/fhir/StructureDefinition/Observation` | 4.0.1 | **validated** |
| Observation | `http://hl7.org/fhir/StructureDefinition/vitalsigns` | 4.0.1 | candidate — blocked on reviewer question Q-A2-1 |
| Observation | `http://hl7.org/fhir/StructureDefinition/bp` | 4.0.1 | candidate — blocked on Q-A2-1 |
| Encounter | `http://hl7.org/fhir/StructureDefinition/Encounter` | 4.0.1 | **validated** |

`vitalsigns` and `bp` are real R4 profiles and `bp` derives from `vitalsigns`,
but claiming them forces `Observation.category = vital-signs` and the panel
code 85354-9 onto the BP fixtures, neither of which concept note §5 specifies.
See DR-102 Q-A2-1.

**Codes.** LOINC `33914-3` (eGFR), `8480-6` (systolic), `8462-4` (diastolic).
Plus the DataAbsentReason, v3-ActCode and v3-ParticipationType codes the
fixtures use. Anything not listed is **rejected**, because concept note §2 says
a code-to-class interpretation needs a reviewed terminology rule.

**Units.** UCUM `mL/min/{1.73_m2}` and `mm[Hg]`. A missing or unrecognised unit
is rejected (concept note §4). `Quantity.unit` is human display text and is
source-only; `Quantity.code` is the normalised binding.

**Renderer.** `fhir_sulo.ingest.fhir_rdf/0.1.0`, canonical form sorted
N-Triples. Deterministic, no network at run time. Rationale, rejected
alternatives and evidence: [DR-101](../docs/fhir-sulo/decisions/DR-101-fhir-rdf-renderer.md).

## In scope vs source-only

`in_scope_elements` are the elements a pivot variable may bind.
`source_only_elements` are rendered into the RDF and retained in the source
layer but are not bound — `MapContract.expected_nonmapped_fields` is populated
from this list.

Source-only is not the same as droppable. The round-trip test detects a change
to `Quantity.unit` just as it detects a change to `Quantity.code`.

Three time elements are kept distinct, per concept note §2:
`Observation.effective[x]` (clinically relevant time), `Observation.issued`
(availability of the result), `meta.lastUpdated` (resource version update).

Temporal precision is derived from the lexical form, and a value matching no
R4 temporal form is **refused**, never guessed. Note that R4 makes the
timezone offset mandatory once a `dateTime` carries a clock time, so
`"2026-09-02T14:00:00"` is not conformant and there is no such thing as an
offsetless R4 timestamp — see `temporal_precision_policy.
offset_is_mandatory_once_a_time_is_present` and DR-102 Q-A2-6. A value coarser
than seconds is `source-only` under
`value_policy.effective_time_coarser_than_seconds` (proposed, pending R3).

## Status and value policy

`status_policy` maps every R4 status value of each resource to `eligible`,
`source-only` or `rejected`; the test suite asserts the declared set is exactly
the R4 value set, so a new status cannot be silently unhandled.
`entered-in-error` is **source-only, not rejected**: concept note §2 says it
suppresses clinical assertions but does not erase the source record.

R3 was answered on 2026-10-01: Observation `final`, `amended` and `corrected`
are `eligible` — the *revision* axis, where a result is complete and verified
and has since been revised. `preliminary` and `registered` stay `source-only`
because they are the *verification* axis, and `entered-in-error` stays
`source-only` because it is retraction rather than revision.
`tests/contracts/ingest/test_eligibility.py::TestEveryObservationStatus`
drives all eight statuses through ingestion and asserts exactly this split, so
widening along the wrong axis fails a test rather than passing quietly.

`value_policy` gives each awkward case an explicit outcome — comparator
present, dataAbsentReason present, both present, unpinned code, unrecognised
unit, unresolvable reference, ambiguous reference, unsupported modifier
extension. Each has at least one negative fixture, and
`test_eligibility.py::test_negative_fixtures_exist_for_every_declared_value_policy`
fails if a rule stops being exercised.

When several findings apply, the most severe wins: `entered-in-error` plus a
comparator is **rejected**, not source-only.

## The element table

Predicate naming follows https://hl7.org/fhir/R4/rdf.html:
`fhir:<TypeThatDefinesTheElement>.<elementName>`. Inherited elements use the
defining base type (`fhir:Resource.id`, `fhir:DomainResource.text`), and
BackboneElement children use the full path from the resource
(`fhir:Observation.component.valueQuantity`). `Observation.component.referenceRange`
is a FHIR contentReference, so its children keep `Observation.referenceRange.*`
predicates even when nested under a component.

Every naming rule here was verified against HL7's own published Turtle, not
inferred: see `fixtures/r4/_oracle/` and the isomorphism test in
`tests/contracts/ingest/test_oracle_conformance.py`.

**The renderer refuses any element or type not in this table.** It cannot
silently drop content because it cannot render content it was not told about.
Widening scope is a reviewable diff to this file.

## Changing a pin

1. Edit the manifest (and the element table, if the scope changes).
2. `python3 fixtures/r4/build.py` to regenerate the derived fixture RDF.
3. `make contracts` — the drift check, the round trip, the mutation suite and
   the binding assertions all run.
4. Record the reason in a DR if the change alters an outcome. Plan §6 rule 6:
   no agent resolves a failed test by weakening the expectation without a
   recorded decision.
