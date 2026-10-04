# Multi-source fixtures — one human at two hospitals

The first corpus in this repo with **more than one source**. Everything under `fixtures/r4/`
comes from a single scope, which is why the hardcoded-scope defect (DR-014) survived 959
passing tests: no fixture could tell a constant from the correct value.

## What is here

| scope | resources | person number |
| --- | --- | --- |
| `mumc-r4` | `Patient/123`, `Observation/egfr-a` (61.5) | `900001` |
| `radboud-r4` | `Patient/987`, `Observation/egfr-b` (55.0) | `900001` |
| `radboud-r4` | `Patient/555`, `Observation/egfr-c` (72.0) | `900009` |

The two `900001` records are **one human** recorded at two hospitals under two unrelated
resource ids. Nothing about `Patient/123` and `Patient/987` connects them except the person
number — that is the point.

`Patient/555` is a different human, present so a passing test means "the index merges the
right people", not "the index merges everyone".

Each Patient also carries a **local MRN**. It is not allowlisted, so it cannot reunify anyone;
it is here because real records carry one and the fixture should look like a real record.

## Why these are not under `fixtures/r4/`

That tree is per map family, with one declared expected outcome and target graph per case, and
tests assert the two sets correspond exactly. These are a *cross-system scenario* rather than
a map case: the interesting artefact is what happens when two separately-mapped graphs are read
together, which no per-case expected graph can express.

## What uses them

`tests/integration/test_multi_source_reunification.py` builds a person index from the Patient
resources, maps both Observations under their own scopes, and asserts the two results attach to
**one** person — and that without the index they do not.

No Patient resource is mapped. The pipeline ingests `Observation` and `Encounter` only; the
Patients are here to be *indexed*, which is the whole reason the index exists (DR-015).
