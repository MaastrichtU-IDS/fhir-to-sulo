"""Gate 2 / Gate 3 acceptance tests for the three ShExMap pairings in `maps/r4/`.

`_engine/` is a TEMPORARY, TEST-ONLY harness that drives the pinned engine:
`shex-validate` for binding extraction (well behaved -- exit 1, parseable JSON
Failure) and `ThreadedMaterializer` through the programmatic API for
materialization, with maxAccepts / maxRepeat / maxSteps / exploreSteps raised
explicitly.  The shipped `shexmap-materialize` is never used (CD-2: it
truncates every repetition to 19 items and exits 0 on fatal and on partial
output).  Agent 4 owns the production driver; this should be deleted when it
lands, and the case modules repointed at it.

The engine runs in Docker.  Tests that need it subclass
`_engine.engine.EngineTestCase`, which skips loudly rather than silently: a
skip is not a pass.  See `maps/r4/README.md` and DR-201.
"""
