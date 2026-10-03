# DR-013 — R12: the participation type types the role node, alongside the practitioner role

**Status:** Reviewer ruling 2026-10-03 (answers R12); applied
**Gate:** 0 (R12) · 3 (Encounter roles)

## The ruling

R12 asked whether `Encounter.participant.type` (`PPRF`) should type the role node. Options were
source-only, participation-type-only, or both. The reviewer chose **both**.

```turtle
ex:practitioner-role-enc-9  a sulo:Role, ex:PractitionerRole, ex:PrimaryPerformerRole ;
    sulo:isFeatureOf ex:person-afd67e8e… .
```

### A concern I raised, and why it does not hold

I argued that two classes make one node "two different roles at once", which the PRO pattern
would model as two Role individuals. **That was overstated.** The two classes are not disjoint,
and OWL multiple classification is ordinary. The node sits in their intersection: *the role held
qua practitioner, and the primary-performer role in this one encounter.* One role, two true
things about it. Recorded because the reviewer answered with the objection in front of them, and
the objection turned out to be weaker than I put it.

### A concern that does hold, and is not resolved by this

The two classes are **not on equal evidential footing**:

| class | derived from | kind of evidence |
| --- | --- | --- |
| `ex:PractitionerRole` | the FHIR **resource type** of the referenced resource | record metadata |
| `ex:PrimaryPerformerRole` | `Encounter.participant.type` via a reviewed table | a coded clinical statement |

DR-010 defended the name `PractitionerRole` on the grounds that it is "derived from what the
record states". That is true in a thin sense and overstated in the sense that matters: it is
derived from **how the record is filed**, which is close to the record→semantics leap §2 exists
to prevent. `PrimaryPerformerRole` has no such problem.

Recorded, not re-litigated. If it is ever revisited, the question is whether
`ex:PractitionerRole` should come off the node and the practitioner-ness live only in the
source layer.

## A separate reviewed table, not an extension of the code table

`policies/participation-type-interpretation.v1.json`, with the same shape and the same status
vocabulary as `code-interpretation.v1.json`. Separate because a participation type answers a
different question: not *what was measured* but *what part did this participant play*.

One default differs, deliberately:

| | observation codes | participation types |
| --- | --- | --- |
| `unknown_code_in_known_system` | `source-only` | **`rejected`** |

An unrecognised *observation* code can sit in the source layer while the rest of the resource
maps — the observation simply is not interpreted. An unrecognised *participation* type cannot:
**the role node is emitted either way**, so ignoring a code that says what the participation was
would assert an under-specified role rather than decline to assert one.

For the same reason `participation_role_class` **raises** rather than returning `None`. A caller
handed a falsy value and carrying on is exactly the silent under-specification this prevents.

`SBJ` and `ATND` are in the table as `proposed` with `role_class: null`. They type nothing, and
they are present so that adding them later is a reviewed edit rather than an invention. Neither
may silently reuse `PPRF`'s class — an attender is not a primary performer.

## The class follows the resource, not a constant

The manifest carries a default for `participationRoleClass`, but the host **overwrites** it with
whatever the reviewed table gives for the code the resource actually carries. Otherwise "the
participation type types the role" would be a constant that merely coincided with the right
answer. `test_changing_the_tables_class_changes_the_emitted_class` pins this by altering the
table and requiring the emitted class to follow.

`static_variables` lists it, because the engine receives it as a run binding, with a note saying
it is host-resolved and not constant.

## Two guards, and only the first fires today

The Encounter source shape admits **only** `PPRF`, so an unreviewed code fails ShEx validation
before the host's terminology lookup is reached — verified by
`test_an_unreviewed_participation_type_is_refused_by_the_schema`.

The policy table's rejection is therefore the **second** guard and is currently **unreachable
through the pipeline**. It is kept deliberately: the schema's value set is expected to widen,
and a code that got past it must still not be handed `PPRF`'s role class by default. This is the
same arrangement as `_refuse_unconsulted_participants` for participant cardinality, and it is
recorded as unreachable rather than presented as live coverage.

## `policy_version` changed, and should have

```
before: fhir-sulo-policies/identity-1.0.0+code-1.0.0+unit-1.0.0+sha256.…
after:  fhir-sulo-policies/identity-1.0.0+code-1.0.0+part-1.0.0+unit-1.0.0+sha256.…
```

A fourth reviewed table that can change emitted triples must appear in the string a `RunRecord`
carries, or a run cannot say which rules produced it. `parse_policy_version` round-trips the new
form, and the bundle digest covers all four tables.

## Vocabulary

`ex:PrimaryPerformerRole` is the **13th** class in the R1 domain vocabulary
(see [DR-008](DR-008-domain-vocabulary-and-its-successor.md)), at
`status: pilot-provisional` like the rest — reviewed at the level of the *rule* (R12), not of
the individual clinical binding.

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
952 passed

$ PYTHONPATH=src .venv/bin/python tools/gate-check.py --all
Gates passing: 5 of 5
```

`test_the_two_roles_are_typed_and_held` was updated from two expected types to three. It is kept
as an **exact-set** assertion rather than relaxed to containment: the point of the check is that
nothing strays onto a role node, and `assertIn` would not notice a fourth type arriving.
