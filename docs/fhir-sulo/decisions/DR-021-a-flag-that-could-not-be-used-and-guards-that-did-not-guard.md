# DR-021 — A flag that could not be used, and three guards that did not guard

**Status:** Found by the second adversarial review 2026-10-04; fixed
**Gate:** 0 · follows [DR-020](DR-020-contained-fusion-alias-shadowing-and-the-canonical-url.md),
whose third fix this corrects

## `--fhir-base` was unusable

DR-020 added a per-source FHIR base so the canonical URL names the source a resource came from.
It was accepted and then **ignored by the renderer**, which still minted the resource IRI from
the pinned manifest base. So the graph's root IRI and the canonical URL disagreed, the engine
was handed a focus node that was not in the graph, and **every resource failed source
validation**:

```
fhir_base=None                        -> MAPPED
fhir_base=https://mumc.example/fhir/  -> SourceValidationFailure: source graph does not
                                         conform to the source schema
```

A flag that cannot be used is worse than an absent one, because it looks available.

`render()` had taken a `base` argument all along; ingest never passed it. One line.

The same bug had a second face: `ReferenceResolver` judged "same server" against the **pinned**
base, so with a per-source base set, a source's own absolute references were refused as
cross-server while references to the placeholder `fhir.example` were accepted as local.
Exactly backwards. The resolver now carries the effective base.

## Three features could be switched off with the suite still green

Review disabled each of these and the whole suite passed, Docker tests included:

| sabotage | before | after |
| --- | --- | --- |
| `run_file` ignores the pipeline's scope | 0 failures | **4** |
| `run_inputs` drops the scope from the graph key | 0 failures | **3** |
| the CLI parses all three flags and discards them | 0 failures | **1** |

The guards that existed were **source-text assertions** — `inspect.getsource(...)` contains a
string — written in the same file whose docstring criticises source-text assertions. A
sabotage that keeps the inspected text walks straight past them, and that is not a hypothetical:
it is how review found these.

The replacements go through `Pipeline.run_file` and the real engine and look at the emitted
graph: two scopes give two person IRIs, two graph keys and two replacement slots; the base
reaches the renderer, so the resource both maps *and* carries the source's URL.

### A note on method

Writing the behavioural version, my first attempt at measuring the sabotages reported
**"0 failures" for all three** — because a shell variable did not survive into the loop and
pytest ran no tests at all. I nearly reported that as "the guards still do not bite". It is the
same unapplied-injection trap recorded in DR-012, hit again, and the only reason it was caught
is that the final line said `no tests ran`. **A fault injection that reports a clean result is
indistinguishable from a passing one unless you check that it ran.**

## The operator path no longer guesses the source

`reference_scope.deployment_mode` is `multi-source`, and ingest still defaulted the scope, so
omitting `--source-scope` fused every source that shared a resource id — silently, because an
entity IRI is keyed on it.

The **operator path** now refuses when the policy says multi-source. The library default stays,
because fixtures and tests have no scope to give and the cost of being wrong there is nothing.
The refusal reads the policy rather than hardcoding the mode, and a test sets the policy to
single-source and requires the refusal to lift.

Three existing tests shelled out to the CLI without a scope and now fail. They were updated to
pass one — they were relying on the unsafe default, which is what the guard is for.

## Verification

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests -q
1062 passed

$ PYTHONPATH=src .venv/bin/python tools/gate-check.py --all
Gates passing: 5 of 5
```
