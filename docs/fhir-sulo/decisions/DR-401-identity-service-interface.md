# DR-401 — Identity service: interface, keying scheme, and ambiguity contract

**Status:** Decided (engineering) + **Review requested** (quality identity)
**Date:** 2026-09-29
**Gate:** 0 (interface) / 1 (deterministic service)
**Owner:** Agent 5 — identity and terminology
**Implements:** concept note §2, §4, §7; plan §2 (Agent 5 row), §3 (`SourceContext`,
`RunRecord`), §5 (acceptance row "Identity"), §7 (risk row "Unknown patient identity
merges two people")

## 1. The published interface

This is the boundary Agent 2 calls and is currently mocking. It is stdlib-only
Python 3.9, importable from `src/`.

```python
from fhir_sulo.identity import (
    IdentityService, IdentityRequest, ReferenceEvidence, SourceScope,
    QualityRequest, EntityIdentity, IdentityUnavailable,
)

svc: IdentityService = IdentityService()                  # loads policies/, pins versions
outcome = svc.resolve(request)            # IdentityResolved | IdentityRejected
qoutcome = svc.resolve_quality(qrequest)  # QualityResolved  | QualityRejected
svc.policy_versions                       # dict for the RunRecord
```

### Inputs (Agent 2 produces these)

```python
@dataclass(frozen=True)
class SourceScope:
    scope_id: str                      # identity scope: the dataset/server
    fhir_base_url: Optional[str] = None

@dataclass(frozen=True)
class ReferenceEvidence:               # one candidate resolution, with how it was found
    evidence_id: str
    kind: str                          # literal-reference | bundle-entry | contained | ...
    source_scope: SourceScope
    resource_type: str                 # "Patient", "Practitioner", ...
    resource_id: str
    canonical_url: Optional[str] = None
    resource_version_id: Optional[str] = None
    detail: Mapping[str, str] = {}     # free-form, recorded in the audit record

@dataclass(frozen=True)
class IdentityRequest:
    reference_literal: str             # "Patient/p123" exactly as written in the source
    expected_resource_types: Tuple[str, ...]
    candidates: Tuple[ReferenceEvidence, ...] = ()   # 0, 1 or many. Order is irrelevant.
    entity_kind: str = "person"
    referring_resource_url: Optional[str] = None     # e.g. the Observation, for audit
```

### Outputs

```python
@dataclass(frozen=True)
class EntityIdentity:
    entity_iri: str
    entity_kind: str
    source_reference_literal: str      # lineage, retained
    source_scope_id: str
    source_resource_type: str
    source_resource_id: str
    source_canonical_url: Optional[str]
    key_scheme: str
    key_inputs: Mapping[str, Any]      # exactly what was hashed; a reviewer can recompute
    rule_id: str
    def lineage(self) -> dict: ...     # includes equivalence_asserted == False

IdentityResolved:  .is_resolved is True,  .identity: EntityIdentity, .record, .unwrap()
IdentityRejected:  .is_resolved is False, .reason_code, .reason, .record, .unwrap() raises
IdentityOutcome = Union[IdentityResolved, IdentityRejected]
```

`.status` on each outcome is `"mapped"` / `"rejected"`, matching
`TransformResult.status` in plan §3 so Agent 4 and Agent 6 can propagate it directly.

Agent 2 needs nothing from this package except these names. Agent 5 imports nothing
from Agent 2.

## 2. Keying scheme, and why it is deterministic

```
entity_iri = base + "person-" + sha256(canonical([
      ["key_scheme",      "fhir-sulo-entity-key/1"],
      ["key_revision",    "1"],
      ["entity_kind",     "person"],
      ["source_scope_id", "synthea-pilot-r4"],
      ["resource_type",   "Patient"],
      ["resource_id",     "p123"],
]))[:32]
```

### Stability under policy change

Because the pinned engine ships no `id()` (Agent 4's CD-1), node identity now comes
from source IRIs plus this service, so Gate 4's "unchanged reprocessing changes no
triples" rests on these keys not moving for incidental reasons.

The key therefore uses **`entity_iri.key_revision`**, a separate sticky field, and
**never** the policy table's semantic `version`. Consequences:

- Bumping any table version, adding a code entry, approving a unit, rewording a rule, or
  the reviewer answering the quality question leaves **every person IRI unchanged**.
  Seven such edits are asserted in `test_key_stability_under_policy_change.py`; each one
  changes `policy_version` and leaves the IRI byte identical.
- Bumping `key_revision` re-keys everything. That is an explicit, breaking decision and
  needs its own DR-4xx record. `PolicyBundle.entity_key_revision` exposes the current
  value so Agent 6 can fold it into a graph key.
- Policy validation now **rejects** a table that puts `policy_version` in
  `key_input_fields`, so this cannot regress silently.

One case where IRIs do move, unavoidably: **changing `quality_identity.mode` changes
every quality IRI**, because the two modes key on different inputs. That is inherent to
the reviewer's choice, not an incidental version bump, and Agent 6 should treat the
answer to Q-ID-1 as a graph-key-affecting event. Person IRIs are unaffected by it.

Determinism comes from five properties, all enforced in one module
(`src/fhir_sulo/policy/canonical.py`) rather than at each call site:

1. **`hashlib.sha256` only.** Python's builtin `hash()` is salted per process by
   `PYTHONHASHSEED`, so it can never reach a key. A static test fails the build if
   `hash(`, `time.time(`, `datetime.now(`, `utcnow(`, `uuid` or `random.` appears
   anywhere under `src/fhir_sulo/`.
2. **Explicit ordered field list.** The key is a list of `[name, value]` pairs in the
   order the policy declares, not a dict, so Python dict insertion order cannot leak in.
   `json.dumps(..., sort_keys=True)` is applied as well.
3. **`ensure_ascii=True`, no whitespace.** The hashed bytes are pure ASCII and
   independent of filesystem or locale encoding.
4. **Unicode NFC normalisation** before hashing, so `pat-é` written as one code point
   and as `e` + combining acute are one entity, not two.
5. **No timestamps, no run ids, no host state.** Deliberately absent from the key *and*
   from the audit record — see §5.

`float` is rejected outright as a key input, because cross-platform `repr` stability is
not something this project should rely on.

Candidate evidence is sorted by content before a key is built, so the order Agent 2
happens to supply candidates in cannot change the output.

This is what makes Gate 4's "unchanged reprocessing changes no triples" achievable on
the identity side.

### Key styles

| `key_style` | Local name | Use |
| --- | --- | --- |
| `scoped-hash` (**default**) | `person-<32 hex>` | Safe by construction. Two sources that both hold `Patient/p123` get different IRIs. |
| `scoped-slug` | `person-<scope>-<id>-<8 hex>` | Readable and still source-scoped. |
| `legacy-concept-note` | `person-p123` | Matches the concept note's `ex:person-p123` literally. **Only** valid when `entity_iri.single_source_scope` names the one permitted scope; a reference from any other scope is rejected with `cross-scope-under-unscoped-key`, and the policy fails to load if the scope is not declared. |

**Integration question for Agent 1 (not the reviewer):** the concept note's schematic
graphs use `ex:person-p123`. If Agent 3's target shapes and Agent 6's expected graphs
want that literal form for fixture readability, set `key_style` to
`legacy-concept-note` with `single_source_scope: "<the fixture scope id>"`. The default
shipped here is `scoped-hash`. This is a fixture-readability choice, not a semantic one;
either way the person IRI is supplied to materialization as a run binding
(concept note §4), so no map hard-codes it.

## 3. How ambiguity is made unignorable

The contract says it must be impossible to *silently* get a person IRI out of an
ambiguous reference, as a type/API property rather than a convention. Four mechanisms,
each tested:

1. **Two distinct return types, not an `Optional`.** `IdentityRejected` has exactly
   three fields — `reason_code`, `reason`, `record` — and no attribute anywhere on it
   holds an IRI. A test asserts the field set is exactly that.
2. **No `Optional`-returning API exists.** A test walks the public surface of
   `fhir_sulo.identity` and fails if any function or method's return annotation mentions
   `Optional` or `None`. A caller therefore cannot write `if iri is None:` and forget the
   else branch, because they are never handed a `None`.
3. **`unwrap()` raises.** On the resolved arm it returns the `EntityIdentity`; on the
   rejected arm it raises `IdentityUnavailable` carrying the reason code and the audit
   record.
4. **Plausible misspellings are loud.** `IdentityRejected.__getattr__` upgrades
   `identity`, `entity_iri`, `iri`, `person`, `person_iri` and `value` from a bare
   `AttributeError` into `IdentityUnavailable`, so the traceback names the real problem.
   `str()` of a rejection cannot be mistaken for an IRI (no `http` in it).

The quality API is protected the same way, plus one more: `QualityRequest.person` is
typed `EntityIdentity`, not `str`, so a quality IRI cannot be requested at all until a
person identity has actually been resolved.

### What is rejected

| Reason code | Situation |
| --- | --- |
| `unresolved-reference` | Reference resolution supplied no candidate. |
| `ambiguous-reference` | Candidates disagree on (scope, resource type, resource id). |
| `unexpected-resource-type` | A candidate is not one of the expected resource types. |
| `incomplete-key-inputs` | A required key input is missing or empty after normalisation. |
| `cross-scope-under-unscoped-key` | The readable key style met a second source scope. |
| `quality-identity-policy-unset` | The reviewer has not chosen a quality identity mode. |

Several pieces of evidence naming the *same* resource is not ambiguity: it resolves
under `ID-R4-concordant-candidates` to the same IRI a single candidate would give. That
is not a merge across identities; it is one triple of key inputs observed more than once.

## 4. Conservative scoping — no merging without evidence

`reference_scope.default` is `source-scoped` and `accepted_merge_evidence` is an empty
list, on purpose. There is no reviewed cross-source merge rule, so no cross-source merge
can occur: `Patient/p123` at site A and `Patient/p123` at site B are two people. A test
fails if that list stops being empty without a decision record.

A resolved FHIR reference is **not** a person-equivalence claim. `EntityIdentity.lineage()`
returns `equivalence_asserted: False` and names `prov:wasDerivedFrom` as the only permitted
lineage predicate; `owl:sameAs` and `owl:equivalentClass` are listed as forbidden between a
FHIR resource and an entity, and a test asserts that neither string appears anywhere in the
identity service's output.

## 5. Audit record

Every call — resolved or rejected — returns a `DecisionRecord` with `service`, `rule_id`,
`status`, `inputs`, `evidence`, `outcome`, `policy_versions`, `reason_code`, `reason`, and
a `decision_id` that is a sha256 over all of it.

It deliberately contains **no timestamp and no run id**. Those are run metadata and belong
in Agent 6's `RunRecord`; embedding them here would make the record irreproducible and
defeat the point of a replayable decision. `outcome.key_inputs` is recorded in full, so a
reviewer can recompute the IRI from the record alone — a test does exactly that.

## 5b. What Agent 6 records

`RunRecord` wants single strings, so the bundle provides them:

| `RunRecord` field | Source | Example |
| --- | --- | --- |
| `policy_version` | `PolicyBundle.policy_version` | `fhir-sulo-policies/identity-1.0.0+code-1.0.0+unit-1.0.0+sha256.6b2c35b7a7c69f3f` |
| `terminology_snapshot` | `PolicyBundle.terminology_snapshot` | `pilot-pinned-subset-2026-09-29` |

One field covers all three tables. It is resolvable: `parse_policy_version(s)` returns
each table's version plus the digest prefix, and `bundle.matches_policy_version(s)` says
whether a checkout is byte-for-byte the bundle a past run used. The frozen contract in
plan §3 does not need amending.

`PolicyBundle.versions` keeps the per-table detail (`entity_key_revision`,
`quality_key_revision`, full `policy_bundle_digest`) and rides in every `DecisionRecord`.

## 6. Test evidence

```
$ .venv/bin/python -m pytest tests/contracts -q
122 passed in 0.54s

$ PYTHONPATH=src python3 -m unittest discover -s tests/contracts -p 'test_*.py'
Ran 18 tests in 0.131s
OK
```

The load-bearing test is `test_replay_across_separate_processes`: it runs
`tests/contracts/identity/replay_probe.py` three times as **separate subprocesses** with
`PYTHONHASHSEED` 0, 1 and 12345, and asserts the canonical JSON of every entity IRI,
quality IRI and decision id is byte identical. An in-process equality check could not
catch a `hash()` dependence, because the salt is fixed for the life of an interpreter.

Fault injection, to show the test is not vacuous: adding `hash("x")` to the key input
made `test_replay_across_separate_processes` fail with *"identity/terminology output
differs across processes"* (different `person-…` IRIs per process) and
`test_no_builtin_hash_in_the_keying_path` fail naming the offending line. Reverting
restored a green suite.

**CI note for the integration lead.** `make contracts` and the CI job run
`python -m unittest discover -s tests/contracts`, which does **not** descend into
`tests/contracts/identity/` or `tests/contracts/terminology/` — those are not importable
packages, and the suites in them use pytest fixtures and `parametrize`. Without a fix,
none of Agent 5's checks would run in CI and Gate 1's "deterministic mock
terminology/identity service" would be satisfied by two directories existing. Two things
were done about it:

1. `tests/contracts/test_identity_terminology_contracts.py` restates the load-bearing
   invariants — including the separate-process replay — in plain `unittest` with stdlib
   only, so the current CI job does execute them (18 tests, no pytest needed). It sits
   beside the other agents' contract tests rather than in Agent 5's subdirectories
   precisely so discovery finds it; flagging that as a deliberate step outside the
   assigned paths.
2. `pytest==7.4.4` is pinned in `requirements-dev.txt`. Adding
   `.venv/bin/python -m pytest tests/contracts -q` to `make contracts` would pick up all
   122 checks; that is the lead's call, since the Makefile and CI are Agent 1's.

Other identity tests: 25 repeated references collapse to one IRI; 500 distinct patients
yield 500 distinct IRIs; the same id at two sources stays two people; Patient and
Practitioner with the same id stay distinct; NFC-equivalent ids do not split one person;
candidate order does not affect the key or the decision id.

## 7. Questions for the reviewer

**Q-ID-1 (the one Gate 0 names) — quality identity.**
Does a quality IRI persist across observations for a patient, or is it keyed per
observation, time and code?

- `persistent-per-person-code` — one quality entity per (person, observable code). The
  same renal-filtration quality IRI is reused across every eGFR observation for that
  person. This is what the concept note's schematic graph (`ex:renal-quality-p123`)
  literally shows. *Risk:* two records the project does not intend to be about one
  persisting quality will merge.
- `per-observation` — keyed by person, code, source observation version and effective
  time, so "independent records do not merge unknowingly" (concept note §4). *Risk:* a
  query for "the patient's renal filtration quality" returns many nodes; trend queries
  must join on the code instead of the quality IRI.

Both are implemented and tested. The shipped default is `null` and **rejects every
request** with `quality-identity-policy-unset`, so nothing can ship a guessed policy.
Agent 3's eGFR and BP target shapes cannot be finished until this is answered.

**Q-ID-2 — is a `Practitioner` the same kind of entity as a `Patient` subject?**
Worked example C makes `ex:clinician-c7` the holder of a `ClinicianRole`. This service
currently keys both with `entity_kind: "person"`, which means a Practitioner and a
Patient resource with the same logical id in the same scope still get different IRIs
(resource type is a key input), but both are typed as people. Confirm that a
`Practitioner` reference should mint a person entity rather than, say, an organisational
agent — and confirm whether a Practitioner who is also a patient in the same source is
allowed to be two entities (currently: yes, because no evidence-backed merge rule exists).

**Q-ID-3 — what counts as recorded evidence for a cross-source merge?**
`accepted_merge_evidence` is empty, so no merge is possible. If the pilot ever needs one
(it does not for Gates 0-4 with synthetic data), the reviewer must say what evidence
licenses it — a shared national identifier, a `Patient.link`, a reviewed master index
entry — and what the resulting graph asserts. Note that even then, the merge is between
two *entities*, never `owl:sameAs` between a FHIR resource and a person.
