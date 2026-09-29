# DR-103 — The interface ingestion needs from the identity service

**Status:** Proposed by Agent 2 (ingestion). **Awaiting confirmation from Agent 5**, who owns the real service and its policy tables.
**Date:** 2026-09-29
**Gate:** 0 / 1

## Why this exists

Plan Gate 1: "Agent 5 supplies a deterministic mock terminology/identity
service." Ingestion must be testable before that lands, and the two agents must
not invent two different shapes for the same call. This DR fixes the shape.

Agent 2 does **not** import Agent 5's code, and Agent 5 is not asked to import
`fhir_sulo.ingest.identity_port`. The shared vocabulary is
`fhir_sulo.contracts.ResolvedReference`, which is already frozen on the
integration branch, so both sides can implement against it independently.

## The call

```python
establish(refs: Mapping[str, ResolvedReference],
          subject_context: SubjectContext) -> Mapping[str, ResolvedReference]
```

`SubjectContext` (defined in `fhir_sulo/ingest/identity_port.py`, moveable to
`contracts/` if Agent 5 prefers):

```python
@dataclass(frozen=True)
class SubjectContext:
    source_server_base: str    # the pinned server base the references resolve against
    dataset_id: str            # the scope within which merging is permitted
    source_resource_iri: str   # the containing resource, needed for contained refs
    source_version_id: str
```

### Contract

1. **Input keys are FHIRPath-ish element locations**, exactly as ingestion
   produced them: `Observation.subject`,
   `Encounter.participant[0].individual`. The output must use the same keys.
2. **Ingestion never proposes an entity IRI and never guesses a person.** Every
   `ResolvedReference` handed in has `entity_iri=None`. This is asserted by
   `test_references.py::test_resolution_alone_never_yields_an_entity_iri` over
   every fixture.
3. **The service fills in** `entity_iri` and `identity_policy_version`, and sets
   `ambiguous` / `ambiguity_reason` where applicable.
4. **Ambiguity is returned, never resolved by picking one.** Setting
   `ambiguous=True` makes `require_entity_iri()` raise, which is the
   acceptance-matrix behaviour "ambiguous identity never silently merges".
5. **`identity_policy_version` is always set**, including when no IRI is
   established. It is the audit trail for *why* nothing was established.
6. **No IRI without a stated rule.** Evidence of kind `unresolvable` or
   `identifier-only` must not receive an `entity_iri` unless the policy version
   names the rule that allowed it.
7. **Pure with respect to ingestion.** Same input, same output. Gate 1 requires
   "running the same map twice yields the same graph identity", and that must
   not be defeated at the identity boundary.

### Evidence kinds the service must branch on

`ReferenceEvidence.kind`, produced by `fhir_sulo.ingest.references`. They are
not equally trustworthy, which is the whole reason the field exists:

| kind | Meaning | Note for policy |
| --- | --- | --- |
| `literal-relative` | `Patient/p123` against the pinned base | the ordinary case |
| `literal-absolute` | `https://other.example/Patient/p9` | names a different server; cross-server merging is a policy call |
| `literal-versioned` | `Patient/p123/_history/2` | see the version question below |
| `contained` | `#p-inline`, resolved inside this resource | has no existence outside its container |
| `identifier-only` | no `reference`, only `Reference.identifier` | a business identifier, not a resolvable target |
| `unresolvable` | dangling `#ref`, `urn:` outside a Bundle, unparseable | no target |
| `ambiguous` | several candidates, e.g. two contained resources sharing an id | must stay ambiguous |

`ReferenceEvidence.notes` carries the human-readable reasons, including a
recorded (not rejected) note when the reference names a different resource type
than the element expects.

## The mock, and the two policy choices baked into it

`fhir_sulo.ingest.MockIdentityService` is the deterministic stand-in Gate 1
needs. It is not a proposal for the real policy, but it does embody two
decisions Agent 5 should explicitly accept or override:

1. **Version-independence.** `Patient/p123` and `Patient/p123/_history/2` are
   the same entity; the `_history` suffix is stripped before keying. Asserted by
   `test_a_version_suffix_does_not_split_an_entity`.
2. **Contained resources are scoped to their container.** Two different
   Observations each containing a Patient with `id="p-inline"` get *different*
   entity IRIs, because a contained resource has no independent existence.
   Asserted by `test_contained_entities_are_scoped_to_their_container`.

Everything else it does is mechanical: an opaque
`{namespace}{prefix}-{sha256(scope_key)[:16]}`. The IRI is opaque on purpose —
`test_entity_iri_is_opaque` asserts that `p123` and `Patient` do not appear in
it, so no downstream code can parse a FHIR id back out and re-introduce the
record/fact confusion.

`RefusingIdentityService` is the **default** when no identity policy is in
force. It establishes nothing, so every `require_entity_iri()` raises. A pilot
run with no reviewed policy therefore claims no people at all, which is the
correct failure mode.

## What Agent 5 needs to confirm

1. The `establish` signature and the `SubjectContext` fields — in particular
   whether `dataset_id` is the right merging scope, or whether it should be a
   richer policy scope object.
2. Whether `SubjectContext` should move into `fhir_sulo.contracts` (Agent 1's
   call, if Agent 5 wants to depend on it).
3. The two policy choices above (version-independence; contained scoping).
4. **Open point:** whether `establish` should also return an *entity class*
   (person / practitioner / contained-record-only). Ingestion does not need it.
   Agent 3's target shapes may, since concept note §6 types the two encounter
   holders differently (`ex:person-p123` vs `ex:clinician-c7`) and that
   distinction has to come from somewhere. Flagging it rather than deciding it.
5. Terminology is **not** covered by this DR. Ingestion currently resolves
   codes and UCUM units against the pinned lists in
   `profiles/fhir-r4-pilot.json` and rejects anything not pinned. If Agent 5
   wants that to go through their resolver instead, the manifest's
   `code_systems` / `unit_systems` blocks are the seam, and this is the moment
   to say so.

## Consequences

- Ingestion can be fully tested today without Agent 5's code.
- If the real service arrives with a different signature, the change is
  confined to `identity_port.py` and `ingest.py`; no fixture, map or target
  shape depends on it.
- No test in the ingestion suite asserts a person identity. They assert that a
  person identity *cannot be obtained* without a policy version.
